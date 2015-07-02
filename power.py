from sys import argv
from sys import stdout
from sys import stderr
import logging

logging.basicConfig(level=logging.DEBUG)

from argparse import ArgumentParser, RawTextHelpFormatter
import numpy
import nbodykit
from nbodykit import plugins

# override file reading option to treat each space-separated word as 
# an argument and ignore comments. Can put option + value on same line
import re

def line_reader(line):
    r = line.find(' #')
    if r >= 0:
        line = line[:r] 
    r = line.find('\t#')
    if r >= 0:
        line = line[:r] 

    words = re.findall(r'(?:[^\s,"]|"(?:\\.|[^"])*")+', line)
    for w in words:
        yield w

# First process the plugins
preparser = ArgumentParser(add_help=False, 
        fromfile_prefix_chars="@")
preparser.add_argument("-X", type=plugins.load, action="append")
# Process the plugins
preparser.exit = lambda a, b: None
preparser.convert_arg_line_to_args = line_reader

ns, unknown = preparser.parse_known_args()

#--------------------------------------------------
# setup the parser
#--------------------------------------------------

# initialize the parser
parser = ArgumentParser("Parallel Power Spectrum Calculator",
        formatter_class=RawTextHelpFormatter,
        fromfile_prefix_chars="@",
        add_help=True,
        description=
     """Calculating matter power spectrum from RunPB input files. 
        Output is written to stdout, in Mpc/h units. 
        PowerSpectrum is the true one, without (2 pi) ** 3 factor. (differ from Gadget/NGenIC internal)
        This script moves all particles to the halo center.
     """,
        epilog=
     """
        This script is written by Yu Feng, as part of `nbodykit'. 
        Other contributors are: Nick Hand, Man-yat Chu
        The author would like thank Marcel Schmittfull for the explanation on cic, shotnoise, and k==0 plane errors.
     """
     )

parser.convert_arg_line_to_args = line_reader

parser.add_argument("-X", action='append', help='path of additional plugins to be loaded' )

# add the positional arguments
parser.add_argument("mode", choices=["2d", "1d"]) 
parser.add_argument("BoxSize", type=float, help='BoxSize in Mpc/h')
parser.add_argument("Nmesh", type=int, help='size of calculation mesh, recommend 2 * Ngrid')
parser.add_argument("output", help='write power to this file. set as `-` for stdout') 

# add the input field types
h = "one or two input fields, specified as:\n\n"
parser.add_argument("inputs", nargs="+", type=plugins.InputPainter.parse, 
                    help=h+plugins.InputPainter.format_help())

# add the optional arguments
parser.add_argument("--binshift", type=float, default=0.0,
        help='Shift the bin center by this fraction of the bin width. Default is 0.0. Marcel uses 0.5. this shall rarely be changed.' )
parser.add_argument("--bunchsize", type=int, default=1024*1024*4,
        help='Number of particles to read per rank. A larger number usually means faster IO, but less memory for the FFT mesh')
parser.add_argument("--remove-cic", default='anisotropic', choices=["anisotropic","isotropic", "none"],
        help='deconvolve cic, anisotropic is the proper way, see http://www.personal.psu.edu/duj13/dissertation/djeong_diss.pdf')
parser.add_argument("--Nmu", type=int, default=5,
        help='the number of mu bins to use' )

# parse
ns = parser.parse_args()

#--------------------------------------------------
# done with the parser. now do the real calculation
#--------------------------------------------------

from nbodykit.measurepower import measure2Dpower, measurepower
from pypm.particlemesh import ParticleMesh
from mpi4py import MPI

def main():

    if MPI.COMM_WORLD.rank == 0:
        print 'importing done'

    # setup the particle mesh object
    pm = ParticleMesh(ns.BoxSize, ns.Nmesh, dtype='f4')

    # paint first input
    Ntot1 = ns.inputs[0].paint(ns, pm)

    # painting
    if MPI.COMM_WORLD.rank == 0:
        print 'painting done'
    pm.r2c()
    if MPI.COMM_WORLD.rank == 0:
        print 'r2c done'

    # do the cross power
    if len(ns.inputs) > 1 and ns.inputs[0] != ns.inputs[1]:
        complex = pm.complex.copy()
        numpy.conjugate(complex, out=complex)

        Ntot2 = ns.inputs[1].paint(ns, pm)
        if MPI.COMM_WORLD.rank == 0:
            print 'painting 2 done'
        pm.r2c()
        if MPI.COMM_WORLD.rank == 0:
            print 'r2c 2 done'
        complex *= pm.complex
        complex **= 0.5

        if MPI.COMM_WORLD.rank == 0:
            print 'cross done'
    # do the auto power
    else:
        complex = pm.complex
    
    # call the appropriate function for 1d/2d cases
    if ns.mode == "1d":
        do1d(pm, complex, ns)

    if ns.mode == "2d":
        do2d(pm, complex, ns)
    
def do2d(pm, complex, ns):
    result = measure2Dpower(pm, complex, ns.binshift, ns.remove_cic, 0, ns.Nmu)
  
    if MPI.COMM_WORLD.rank == 0:
        print 'measure'

    if pm.comm.rank == 0:
        storage = plugins.PowerSpectrumStorage.get(ns.mode, ns.output)
        storage.write(dict(zip(['k','mu','power','modes','edges'], result)))

def do1d(pm, complex, ns):
    result = measurepower(pm, complex, ns.binshift, ns.remove_cic, 0)

    if MPI.COMM_WORLD.rank == 0:
        print 'measure'

    if pm.comm.rank == 0:
        storage = plugins.PowerSpectrumStorage.get(ns.mode, ns.output)
        storage.write(result)
        
main()
