from ..core.utils import write_xyz, eof
from ..core.results import Results

import re
import os
import subprocess

__all__ = ['GamessResults']

class GamessResults(Results):
    """Class for obtaining results from Gamess simulations. This class requires
    a log file to be read.
    Usage:
        >>> results = Gamess_results(using = 'filename.log')

    Note: assumes that FMO has been used.
    May have to change in future, and write methods for both non-FMO and FMO
    calculations.

    Currently, these methods look for FMO3 data primarily, with an FMO2 fall
back if not found.

    Instances of this class have the following attributes:

    * ``log`` -- filename of the log file of the calculation
    * ``basis`` -- basis set of the calculation, as this class is assumed to be
    * used for ab initio calculations. This attribute may be read from the
    * input file i.e. set as gamess.input.basis = 'CCT')
    * ``coords`` -- coordinates of system, in xyz format
    
    Currently all methods to find energy return the last occurrence of that energy- needs amending to grep every
instance, really. Simple fix; instead of returning values, store in list and return the list, maybe
store the iteration number.
    """
    def __init__(self, log):
        super().__init__(log)

    ################################
    #                              #
    #      CHECK IF COMPLETED      #
    #                              #
    ################################

    def __repr__(self):
        return self.log # debugging

    __str__ = __repr__

    def completed(self):
        found = False
        for line in eof(self.log, 0.1):
            if 'EXECUTION OF GAMESS TERMINATED NORMALLY' in line:
                found = True
        return found
        
        ####NEEDS WORK####
        # CURRENTLY IF TERMINATES ABNORMALLY, RESULTS FROM THE CALC
        # ARE NOT RETURNED, EVEN IF THERE

    # call like this:
    # if not self.completed():
    #     self.get_error() 
    # cutoff in middle of run with no explanation- memory error
    def memory_error(self):
        print('Memory Error- check allocation before resubmitting')

    def get_error(self):
        super().get_error()
        if self.is_optimisation():
            no_equil = True
            for line in self.read():
                # check for equilibrium coords
                if 'EQUILIBRIUM GEOMETRY LOCATED' in line:
                    no_equil = False    
            if no_equil:
                return 'No equilibrium geometry found- need to resubmit with rerun.xyz'
            else:
                self.memory_error() # last resort

 
    ################################
    #                              #
    #         IF COMPLETED         #
    #                              #
    ################################

    def get_runtype(self):
        """Returns type of calculation ran"""
        for line in self.read():
            if 'RUNTYP=' in line.upper():
                parts = line.split()
                for p in parts:
                    if 'RUNTYP=' in p:
                        return p.split('=')[1].lower()
        # finds the first instance then breaks out of loop
    
    def get_fmo_level(self):
        """Returns level of FMO calculation ran"""
        for line in self.read():
            if 'NBODY' in line:
              return int(line.split()[-1].split('=')[-1]) # FMO2 or 3
        return 0
        
    def get_equil_coords(self, output = None):
        # find the parent dir for the system, regardless of opt/rerun
        # find the dir with complex/ionic/frags (for frags in subdir) /opt/spec/hess (not frags in
        # subdir)
        # first time that comes up- that's the parent!
        import re
        equil = []
        rerun = []
        regex = "[A-Za-z]{1,2}(\s*\D?[0-9]{1,3}\.[0-9]{1,10}){4}"
        found_equil = False
        found_some = False
        par_dir = []
        for part in self.path.split('/'):
            if part in ('opt', 'spec', 'hess'):
                break
            else:
                par_dir.append(part)
        MOLECULE_PARENT_DIR = '/'.join(par_dir)
        for line in self.read():
            if 'EQUILIBRIUM GEOMETRY LOCATED' in line:
                found_equil = True
            if 'COORDINATES OF ALL ATOMS ARE (ANGS)' in line: #store every coord list
                found_some = True
                if len(rerun) > 0: # from last run, remove those coords
                    rerun = []
            if found_equil:
                if re.search(regex, line):
                    if line.endswith('\n'):
                        equil.append(line[:-1]) # drop newline char
                    else:
                        equil.append(line)
            if found_some:
                if re.search(regex, line):
                    if line.endswith('\n'):
                        rerun.append(line[:-1]) # drop newline char
                    else:
                        rerun.append(line)
            if line is '\n':
                found_equil = False
                found_some = False
       
        if len(equil) > 0:
            print('found equilibrium!')
            newdir = os.path.join(MOLECULE_PARENT_DIR, 'spec')
            newname = self.basename + '_equil.xyz'
            if not os.path.isdir(newdir):
                os.mkdir(newdir)
            write_xyz(equil, os.path.join(newdir, newname))
        else:
            if len(rerun) > 0:
                print(f'equilibrium not found.\nNeeds resubmitting. Coords stored in {self.path}/rerun/rerun.xyz')
                rerun_dir = os.path.join(self.path, 'rerun')
                if not os.path.exists(rerun_dir): 
                    os.mkdir(rerun_dir)
                write_xyz(rerun, os.path.join(rerun_dir, 'rerun.xyz'))
            else:
                print('No iterations were cycled through!')   
    
    def is_optimisation(self):
        return self.get_runtype() == 'optimize'
    
    def is_spec(self):
        return self.get_runtype() == 'energy'

    def is_hessian(self):
        return self.get_runtype() == 'hessian'

    ################################
    #                              #
    #      AB INITIO ENERGIES      #
    #                              #
    ################################

    
    def mp2_data(self, mp2_type):
        """
        Returns Hartree Fock and MP2 data. Returns the last instance of both.
        """
        HF = ''
        MP2 = ''
        for line in eof(self.log, 0.2): # last values only
            if 'Euncorr HF' in line:
                HF = float(line.split()[-1])
            if f'E corr {mp2_type}' in line:
                MP2 = float(line.split()[-1])

        return HF, MP2

    @property
    def total_energy(self):
        """
        Returns last occurrence of total energy.
        """
        total = ''
        for line in self.read():
            if 'TOTAL ENERGY =' in line:
                total = line.split()[-1]
        return float(total)

    @property 
    def basis(self):
        """
        Returns basis set.
        """
        def raw_basis():
            for line in self.read():
                if 'INPUT CARD> $BASIS' in line:
                    return line.split()[-2].split('=')[1]
        
        basis = raw_basis()
        change_basis = {'CCD'  : 'cc-pVDZ',
                        'CCT'  : 'cc-pVTZ',
                        'CCQ'  : 'cc-pVQZ',
                        'aCCD' : 'aug-cc-pVDZ',
                        'aCCT' : 'aug-cc-pVTZ',
                        'aCCQ' : 'aug-cc-pVQZ'}
        return change_basis.get(self.basis, self.basis) # if self.basis not in dict, return self.basis
    
    def non_fmo_mp2_data(self):
        """
        Returns value of E(0) as HF, E(2S) as the opposite spin energy and
        E(2T) as same spin energy. Then user can scale energies accordingly.
        """
        HF = ''
        MP2_opp = ''
        MP2_same = ''
        for line in eof(self.log, 0.2):
            line = line.split()
            if 'E(0)=' in line:
                HF = line[-1]
            if 'E(2S)=' in line:
                MP2_opp = line[-1]
            if 'E(2T)=' in line:
                MP2_same = line[-1]

        HF, MP2_opp, MP2_same = map(float, (HF, MP2_opp, MP2_same))
        return HF, MP2_opp, MP2_same

    @property
    def energy_type(self):
        """
        Returns energy type, i.e. HF, DFT, MP2
        """
        dft = False
        fmo = False
        mp2 = False
        scs = False
        for line in self.read():
            if 'FMO' in line:
                fmo = True
            if 'MPLEVL' in line:
                mp2 = True
            if 'SCS' in line:
                scs = True
            if 'DFT' in line:
                dft = True
            if 'RUN TITLE' in line:
                break # by this point, all data required is specified
        types = {
                 'fmo_scs': (fmo, scs),
                 'fmo_mp2': (fmo, mp2),
                 'fmo_dft': (fmo, dft),
                 'fmo_hf': (fmo,),
                 'scs': (scs,),
                 'mp2': (mp2,),
                 'dft': (dft,)
                }
        for run, possible_runs in types.items():
            if all(r for r in possible_runs):
                return run
        else:
            return 'hf'  

    def get_data(self):
        """
        Returns the last occurrence of FMO energies 
        (FMO3 given if available, else FMO2), MP2 correlation energies
        and HF energies. Works because FMO3 values are printed 
        after FMO2, and the function returns the last 
        value printed.
        """
        print('type', self.energy_type)
        if self.energy_type == 'fmo_scs':
            HF, MP2 = self.mp2_data('SCS')
            MP2_opp = 'NA'
            MP2_same = 'NA'
        elif self.energy_type == 'fmo_mp2':
            HF, MP2 = self.mp2_data('MP2')
            MP2_opp = 'NA'
            MP2_same = 'NA'
        elif self.energy_type in ('mp2', 'scs'):
            HF, MP2_opp, MP2_same = self.non_fmo_mp2_data()
            MP2 = 'NA'
        elif 'dft' in self.energy_type or 'hf' in self.energy_type:
            HF = self.total_energy
            MP2 = 'NA'
            MP2_opp = 'NA'
            MP2_same = 'NA'
            
        return self.file, self.path, self.basis, HF, MP2, MP2_opp, MP2_same    

    @property
    def multiplicity(self):
        for line in self.read():
            if 'SPIN MULTIPLICITY' in line:
                return int(line.split()[-1])

    #################
    ### HOMO-LUMO ###
    #################

    @property
    def num_orbitals_occupied(self):
        for line in self.read():
            if 'ORBITALS ARE OCCUPIED' in line:
                return int(line.split()[0])

    def _neutral_homo_lumo(self):
        """
        Finds HOMO-LUMO gap for jobs of singlet multiplicity
        """
        found = False
        orbital_energies = []
        for line in self.read():
            if 'EIGENVECTORS' in line:
                found = True
            if 'CPU' in line:
                found = False
            if found:
                if re.search('^(\s+-?[0-9]+.[0-9]+){1,5}$', line):
                    orbital_energies += [float(i) for i in line.split()]
                    # save time
                    if len(orbital_energies) > self.num_orbitals_occupied + 1:
                        break
        homo = orbital_energies[self.num_orbitals_occupied - 1]
        lumo = orbital_energies[self.num_orbitals_occupied]
        return homo, lumo

    def _reduced_homo_lumo(self):
        """
        Finds SOMO-LUMO gap for jobs of doublet multiplicity.
        """
        # TODO
        return 0,0 

    @property
    def homo_lumo_gap(self):
        """
        Prints the HOMO-LUMO gap for. Finds SOMO-LUMO if multiplicity is 2.
        Returns `self.multiplicity`, SOMO/HOMO (Eh), LUMO (Eh) and the gap (eV).
        """
        hartrees_to_eV = 27.21 # I'm assuming that a.u. are Hartrees
        def calculate_gap(homo, lumo):
            gap_in_hartrees = lumo - homo
            gap_in_eV = gap_in_hartrees * hartrees_to_eV
            return gap_in_hartrees, gap_in_eV

        if self.multiplicity == 1:
            homo, lumo = self._neutral_homo_lumo()
            gap_in_hartrees, gap_in_eV = calculate_gap(homo, lumo)
            transition = 'HOMO-LUMO'
        elif self.multiplicity == 2:
            homo, lumo = self._reduced_homo_lumo() # here homo is somo
            gap_in_hartrees, gap_in_eV = calculate_gap(homo, lumo)
            transition = 'SOMO-LUMO'
        else:
            print(f'Error: Only singlet/doublet multiplicities have been accounted for. Ignoring {self.log}')
        return {'File': self.file,
                'Path': self.path,
                'Multiplicity': self.multiplicity, 
                'Transition': transition, 
                'HOMO/SOMO (Eh)': homo, 
                'LUMO (Eh)': lumo, 
                'Gap (eV)': gap_in_eV}

            
    ################################
    #                              #
    #     VIBRATIONAL ANALYSIS     #
    #                              #
    ################################

    # create and visualise freq modes/ IR spectra    

    def vib_get_geom(self):
        pass
    
    def vib_get_vibs(self):
        vibs = {}
        pass
        # vibs[mode] = [list of vibs for each atom]
        # one set for each mode
    
    def vib_get_intensity(self):
        ints = {}
        pass
        # ints[mode] = [list of ints for each atom]

    def vib_get_coords(self):
        coords = {}
        pass
        # coords[mode] = [list of coords, one coord for each atom]
