#!/usr/bin/env python

# Python script created by Lucas Hale

# Standard library imports
from __future__ import division, absolute_import, print_function
import os
import sys
import uuid
import glob
import shutil
import random
import datetime
from copy import deepcopy

# http://www.numpy.org/
import numpy as np 

# https://github.com/usnistgov/DataModelDict 
from DataModelDict import DataModelDict as DM

# https://github.com/usnistgov/atomman 
import atomman as am
import atomman.lammps as lmp
import atomman.unitconvert as uc

# https://github.com/usnistgov/iprPy
import iprPy

# Define calc_style and record_style
calc_style = 'dislocation_monopole'
record_style = 'calculation_dislocation_monopole'

def main(*args):
    """Main function called when script is executed directly."""

    # Read input file in as dictionary
    with open(args[0]) as f:
        input_dict = iprPy.tools.parseinput(f, allsingular=True)
    
    # Interpret and process input parameters
    process_input(input_dict, *args[1:])
   
    results_dict = dislocationmonopole(input_dict['lammps_command'],
                                       input_dict['initialsystem'],
                                       input_dict['potential'],
                                       input_dict['symbols'],
                                       input_dict['burgersvector'],
                                       input_dict['C'],
                                       axes = input_dict['axes'],
                                       mpi_command = input_dict['mpi_command'],
                                       etol = input_dict['energytolerance'],
                                       ftol = input_dict['forcetolerance'],
                                       maxiter = input_dict['maxiterations'],
                                       maxeval = input_dict['maxevaluations'],
                                       dmax = input_dict['maxatommotion'],
                                       annealtemp =  input_dict['annealtemperature'],
                                       randomseed = input_dict['randomseed'],
                                       bshape = input_dict['dislocation_boundaryshape'],
                                       bwidth = input_dict['boundarywidth'])
    
    # Save data model of results
    results = iprPy.buildmodel(record_style, 'calc_' + calc_style, input_dict,
                               results_dict)

    with open('results.json', 'w') as f:
        results.json(fp=f, indent=4)
    
def dislocationmonopole(lammps_command, system, potential, symbols, burgers,
                        C, mpi_command=None, axes=None, randomseed=None,
                        etol=0.0, ftol=0.0, maxiter=10000, maxeval=100000,
                        dmax=uc.set_in_units(0.01, 'angstrom'),
                        annealtemp=0.0, bshape='circle',
                        bwidth=uc.set_in_units(10, 'angstrom')):
    """
    Creates and relaxes a dislocation monopole system.
    
    Parameters
    ----------
    lammps_command :str
        Command for running LAMMPS.
    system : atomman.System
        The bulk system to add the defect to.
    potential : atomman.lammps.Potential
        The LAMMPS implemented potential to use.
    symbols : list of str
        The list of element-model symbols for the Potential that correspond to
        system's atypes.
    burgers : list or numpy.array of float
        The burgers vector for the dislocation being added.
    C : atomman.ElasticConstants
        The system's elastic constants.
    mpi_command : str or None, optional
        The MPI command for running LAMMPS in parallel.  If not given, LAMMPS
        will run serially.
    axes : numpy.array of float or None, optional
        The 3x3 axes used to rotate the system by during creation.  If given,
        will be used to transform burgers and C from the standard
        crystallographic orientations to the system's Cartesian units.
    randomseed : int or None, optional
        Random number seed used by LAMMPS in creating velocities and with
        the Langevin thermostat.  (Default is None which will select a
        random int between 1 and 900000000.)
    etol : float, optional
        The energy tolerance for the structure minimization. This value is
        unitless. (Default is 0.0).
    ftol : float, optional
        The force tolerance for the structure minimization. This value is in
        units of force. (Default is 0.0).
    maxiter : int, optional
        The maximum number of minimization iterations to use (default is 
        10000).
    maxeval : int, optional
        The maximum number of minimization evaluations to use (default is 
        100000).
    dmax : float, optional
        The maximum distance in length units that any atom is allowed to relax
        in any direction during a single minimization iteration (default is
        0.01 Angstroms).
    annealtemp : float, optional
        The temperature to perform a dynamic relaxation at. (Default is 0.0,
        which will skip the dynamic relaxation.)
    bshape : str, optional
        The shape to make the boundary region.  Options are 'circle' and
        'rect' (default is 'circle').
    bwidth : float, optional
        The minimum thickness of the boundary region (default is 10
        Angstroms).
    
    Returns
    -------
    dict
        Dictionary of results consisting of keys:
        
        - **'dumpfile_base'** (*str*) - The filename of the LAMMPS dump file
          for the relaxed base system.
        - **'symbols_base'** (*list of str*) - The list of element-model
          symbols for the Potential that correspond to the base system's
          atypes.
        - **'Stroh_preln'** (*float*) - The pre-logarithmic factor in the 
          dislocation's self-energy expression.
        - **'Stroh_K_tensor'** (*numpy.array of float*) - The energy
          coefficient tensor based on the dislocation's Stroh solution.
        - **'dumpfile_disl'** (*str*) - The filename of the LAMMPS dump file
          for the relaxed dislocation monopole system.
        - **'symbols_disl'** (*list of str*) - The list of element-model
          symbols for the Potential that correspond to the dislocation
          monopole system's atypes.
        - **'E_total_disl'** (*float*) - The total potential energy of the
          dislocation monopole system.
    """
    # Initialize results dict
    results_dict = {}
    
    # Save initial perfect system
    am.lammps.atom_dump.dump(system, 'base.dump')
    results_dict['dumpfile_base'] = 'base.dump'
    results_dict['symbols_base'] = symbols

    # Solve Stroh method for dislocation
    stroh = am.defect.Stroh(C, burgers, axes=axes)
    results_dict['Stroh_preln'] = stroh.preln
    results_dict['Stroh_K_tensor'] = stroh.K_tensor
    
    # Generate dislocation system by displacing atoms
    disp = stroh.displacement(system.atoms.view['pos'])
    system.atoms.view['pos'] += disp

    system.wrap()
    
    # Apply fixed boundary conditions
    system, symbols = disl_boundary_fix(system, symbols, bwidth, bshape)
    
    # Relax system
    relaxed = disl_relax(lammps_command, system, potential, symbols,
                         mpi_command = mpi_command, 
                         annealtemp = annealtemp,
                         etol = etol, 
                         ftol = ftol, 
                         maxiter = maxiter, 
                         maxeval = maxeval)
    
    # Save relaxed dislocation system with original box vects
    system_disl = am.load('atom_dump', relaxed['dumpfile'])[0]

    system_disl.box_set(vects=system.box.vects, origin=system.box.origin)
    lmp.atom_dump.dump(system_disl, 'disl.dump')
    results_dict['dumpfile_disl'] = 'disl.dump'
    results_dict['symbols_disl'] = symbols
    
    results_dict['E_total_disl'] = relaxed['E_total']
    
    # Cleanup files
    os.remove('0.dump')
    os.remove(relaxed['dumpfile'])
    for dumpjsonfile in glob.iglob('*.dump.json'):
        os.remove(dumpjsonfile)
    
    return results_dict

def disl_boundary_fix(system, symbols, bwidth, bshape='circle'):
    """
    Creates a boundary region by changing atom types.
    
    Parameters
    ----------
    system : atomman.System
        The system to add the boundary region to.
    symbols : list of str
        The list of element-model symbols for the Potential that correspond to
        system's atypes.
    bwidth : float
        The minimum thickness of the boundary region.
    bshape : str, optional
        The shape to make the boundary region.  Options are 'circle' and
        'rect' (default is 'circle').
    """
    natypes = system.natypes
    atypes = system.atoms_prop(key='atype')
    pos = system.atoms_prop(key='pos')
    
    if bshape == 'circle':
        # Find x or y bound closest to 0
        smallest_xy = min([abs(system.box.xlo), abs(system.box.xhi),
                           abs(system.box.ylo), abs(system.box.yhi)])
        
        radius = smallest_xy - bwidth
        xy_mag = np.linalg.norm(system.atoms_prop(key='pos')[:,:2], axis=1)        
        atypes[xy_mag > radius] += natypes
    
    elif bshape == 'rect':
        index = np.unique(np.hstack((np.where(pos[:,0] < system.box.xlo + bwidth),
                                     np.where(pos[:,0] > system.box.xhi - bwidth),
                                     np.where(pos[:,1] < system.box.ylo + bwidth),
                                     np.where(pos[:,1] > system.box.yhi - bwidth))))
        atypes[index] += natypes
           
    else:
        raise ValueError("Unknown boundary shape type! Enter 'circle' or 'rect'")

    new_system = deepcopy(system)
    new_system.atoms_prop(key='atype', value=atypes)
    symbols = symbols * 2
    
    return new_system, symbols
        
def disl_relax(lammps_command, system, potential, symbols, 
               mpi_command=None, annealtemp=0.0, randomseed=None,
               etol=0.0, ftol=1e-6, maxiter=10000, maxeval=100000,
               dmax=uc.set_in_units(0.01, 'angstrom')):
    """
    Sets up and runs the disl_relax.in LAMMPS script for relaxing a
    dislocation monopole system.
    
    Parameters
    ----------
    lammps_command :str
        Command for running LAMMPS.
    system : atomman.System
        The system to perform the calculation on.
    potential : atomman.lammps.Potential
        The LAMMPS implemented potential to use.
    symbols : list of str
        The list of element-model symbols for the Potential that correspond to
        system's atypes.
    mpi_command : str, optional
        The MPI command for running LAMMPS in parallel.  If not given, LAMMPS
        will run serially.
    annealtemp : float, optional
        The temperature to perform a dynamic relaxation at. (Default is 0.0,
        which will skip the dynamic relaxation.)
    randomseed : int or None, optional
        Random number seed used by LAMMPS in creating velocities and with
        the Langevin thermostat.  (Default is None which will select a
        random int between 1 and 900000000.)
    etol : float, optional
        The energy tolerance for the structure minimization. This value is
        unitless. (Default is 0.0).
    ftol : float, optional
        The force tolerance for the structure minimization. This value is in
        units of force. (Default is 0.0).
    maxiter : int, optional
        The maximum number of minimization iterations to use (default is 
        10000).
    maxeval : int, optional
        The maximum number of minimization evaluations to use (default is 
        100000).
    dmax : float, optional
        The maximum distance in length units that any atom is allowed to relax
        in any direction during a single minimization iteration (default is
        0.01 Angstroms).
        
    Returns
    -------
    dict
        Dictionary of results consisting of keys:
        
        - **'logfile'** (*str*) - The name of the LAMMPS log file.
        - **'dumpfile'** (*str*) - The name of the LAMMPS dump file
          for the relaxed system.
        - **'E_total'** (*float*) - The total potential energy for the
          relaxed system.
    """
    
    # Get lammps units
    lammps_units = lmp.style.unit(potential.units)
    
    #Get lammps version date
    lammps_date = iprPy.tools.check_lammps_version(lammps_command)['lammps_date']
    
    # Define lammps variables
    lammps_variables = {}
    system_info = lmp.atom_data.dump(system, 'system.dat',
                                     units=potential.units,
                                     atom_style=potential.atom_style)
    lammps_variables['atomman_system_info'] = system_info
    lammps_variables['atomman_pair_info'] = potential.pair_info(symbols)
    ann_info = anneal_info(annealtemp, randomseed, potential.units)
    lammps_variables['anneal_info'] = ann_info
    lammps_variables['etol'] = etol
    lammps_variables['ftol'] = uc.get_in_units(ftol, lammps_units['force'])
    lammps_variables['maxiter'] = maxiter
    lammps_variables['maxeval'] = maxeval
    lammps_variables['dmax'] = dmax
    lammps_variables['group_move'] = ' '.join(np.array(range(1,
                                                       system.natypes//2+1),
                                              dtype=str))
    
    # Set dump_modify format based on dump_modify_version
    if lammps_date < datetime.date(2016, 8, 3):
        lammps_variables['dump_modify_format'] = '"%d %d %.13e %.13e %.13e %.13e"'
    else:
        lammps_variables['dump_modify_format'] = 'float %.13e'
    
    # Write lammps input script
    template_file = 'disl_relax.template'
    lammps_script = 'disl_relax.in'
    with open(template_file) as f:
        template = f.read()
    with open(lammps_script, 'w') as f:
        f.write(iprPy.tools.filltemplate(template, lammps_variables,
                                         '<', '>'))

    # Run LAMMPS
    output = lmp.run(lammps_command, lammps_script, mpi_command,
                     return_style='object')
    thermo = output.simulations[-1]['thermo']
    
    # Extract output values
    results = {}
    results['logfile'] = 'log.lammps'
    results['dumpfile'] = '%i.dump' % thermo.Step.values[-1] 
    results['E_total'] = uc.set_in_units(thermo.PotEng.values[-1],
                                         lammps_units['energy'])
    
    return results

def anneal_info(temperature=0.0, randomseed=None, units='metal'):
    """
    Generates LAMMPS commands for thermo anneal.
    
    Parameters
    ----------
    temperature : float, optional
        The temperature to relax at (default is 0.0).
    randomseed : int or None, optional
        Random number seed used by LAMMPS in creating velocities and with
        the Langevin thermostat.  (Default is None which will select a
        random int between 1 and 900000000.)
    units : str, optional
        The LAMMPS units style to use (default is 'metal').
    
    Returns
    -------
    str
        The generated LAMMPS input lines for performing a dynamic relax.
        Will be '' if temperature==0.0.
    """
    # Get lammps units
    lammps_units = lmp.style.unit(units)
    
    # Return nothing if temperature is 0.0 (don't do thermo anneal)
    if temperature == 0.0:
        return ''
    
    # Generate velocity, fix nvt, and run LAMMPS command lines
    else:
        if randomseed is None:
            randomseed = random.randint(1, 900000000)
            
        start_temp = 2 * temperature
        tdamp = 100 * lmp.style.timestep(units)
        timestep = lmp.style.timestep(units)
        info = '\n'.join([
            'velocity move create %f %i mom yes rot yes dist gaussian' % (start_temp, randomseed),
            'fix nvt all nvt temp %f %f %f' % (temperature, temperature,
                                               tdamp),
            'timestep %f' % (timestep),
            'thermo 10000',
            'run 10000',
            ])

    return info
    
def process_input(input_dict, UUID=None, build=True):
    """
    Processes str input parameters, assigns default values if needed, and
    generates new, more complex terms as used by the calculation.
    
    Parameters
    ----------
    input_dict :  dict
        Dictionary containing the calculation input parameters with string
        values.  The allowed keys depends on the calculation style.
    UUID : str, optional
        Unique identifier to use for the calculation instance.  If not 
        given and a 'UUID' key is not in input_dict, then a random UUID4 
        hash tag will be assigned.
    build : bool, optional
        Indicates if all complex terms are to be built.  A value of False
        allows for default values to be assigned even if some inputs 
        required by the calculation are incomplete.  (Default is True.)
    """
    
    # Set calculation UUID
    if UUID is not None: 
        input_dict['calc_key'] = UUID
    else: 
        input_dict['calc_key'] = input_dict.get('calc_key', str(uuid.uuid4()))
    
    # Set default input/output units
    iprPy.input.units(input_dict)
    
    # These are calculation-specific default strings
    input_dict['sizemults'] = input_dict.get('sizemults', '-10 10 -10 10 0 3')
    input_dict['boundaryshape'] = input_dict.get('dislocation_boundaryshape',
                                                  'circle')
    input_dict['forcetolerance'] = input_dict.get('forcetolerance',
                                                  '1.0e-6 eV/angstrom')
    
    # These are calculation-specific default booleans
    # None for this calculation
    
    # These are calculation-specific default integers
    input_dict['randomseed'] =     int(input_dict.get('randomseed',
                                       random.randint(1, 900000000)))
    
    # These are calculation-specific default unitless floats
    input_dict['annealtemperature'] = float(input_dict.get('annealtemperature',
                                                           0.0))
    input_dict['boundarywidth'] = float(input_dict.get('dislocation_boundarywidth', 3.0))
    
    # These are calculation-specific default floats with units
    # None for this calculation
    
    # Check lammps_command and mpi_command
    iprPy.input.commands(input_dict)
    
    # Set default system minimization parameters
    iprPy.input.minimize(input_dict)
    
    # Load potential
    iprPy.input.potential(input_dict)
    
    # Load ucell system
    iprPy.input.systemload(input_dict, build=build)
    
    # Load dislocation parameters
    iprPy.input.dislocationmonopole(input_dict)
    
    # Load elastic constants
    iprPy.input.elasticconstants(input_dict, build=build)
    
    # Construct initialsystem by manipulating ucell system
    iprPy.input.systemmanipulate(input_dict, build=build)

if __name__ == '__main__':
    main(*sys.argv[1:])