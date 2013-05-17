#!/usr/bin/env python
#######################################################################################
## TODO:
## - add bulge components
## - use more realistic (COSMOS) distribution of intrinsic ellipticities?
## - add variations over galaxy size parameters (and others?)
#######################################################################################

import sys
import os
import math
import argparse

import logging
import galsim
import pyfits

twopi = 2*math.pi
deg2rad = math.pi/180.
deg2arcsec = 3600.
arcmin2arcsec = 60.

"""
Creates a source object with the specified parameters.
"""
def createSource(flux,xc,yc,hlr,q,beta,g1,g2):
    source = galsim.Exponential(flux = flux, half_light_radius = hlr)
    source.applyShear(q = q, beta = beta*galsim.radians)
    source.applyShear(g1 = g1, g2 = g2)
    source.applyShift(dx = xc, dy = yc)
    return source

"""
Renders the specified source convolved with a psf (which might be None)
and pixel response into a postage stamp with the specified bounding box.
"""
def createStamp(src,psf,pix,bbox):
    stamp = galsim.ImageD(bbox)
    if psf == None:
        obj = galsim.Convolve([src,pix], real_space = True)
    else:
        obj = galsim.Convolve([src,psf,pix])
    obj.draw(image = stamp)
    return stamp

def main():

    # Parse command-line args
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", default = 'gcat.dat',
        help = "name of input catalog to read")
    parser.add_argument("-o","--output", default = 'catout',
        help = "base name of output files to write")
    parser.add_argument("-x","--x-center", type = float, default = 2048.,
        help = "central RA of image (pixels)")
    parser.add_argument("-y","--y-center", type = float, default = -2048.,
        help = "central DEC of image (pixels)")
    parser.add_argument("--width", type = int, default = 512,
        help = "image width (pixels)")
    parser.add_argument("--height", type = int, default = 512,
        help = "image height (pixels)")
    parser.add_argument("--margin", type = float, default = 10.,
        help = "size of surrounding margin where objects might leak into image (arcmins)")
    parser.add_argument("--pixel-scale", type = float, default = 0.2,
        help = "pixel scale (arscecs/pixel)")
    parser.add_argument("--psf-fwhm", type = float, default = 0.7,
        help = "psf full-width-half-max in arcsecs")
    parser.add_argument("--psf-beta", type = float, default = 3.0,
        help = "psf Moffat parameter beta")
    parser.add_argument("--flux-norm", type = float, default = 711.,
        help = "total flux in ADU for a typical galaxy of AB mag 24")
    parser.add_argument("--nvisits", type = int, default = 230,
        help = "number of visits to simulate")
    parser.add_argument("--sky-level", type = float, default = 780.778,
        help = "average sky level to simulate (ADU/pixel)")
    parser.add_argument("--g1", type = float, default = 0.,
        help = "Constant shear component g1 to apply")
    parser.add_argument("--g2", type = float, default = 0.,
        help = "Constant shear component g2 to apply")
    parser.add_argument("--partials", action = "store_true",
        help = "Calculate and save partial derivatives with respect to object parameters")
    parser.add_argument("--partials-order", type = int, default = 1,
        help = "Order of finite difference equation to use for evaluating partials")
    args = parser.parse_args()

    # Configure the GalSim logger
    logging.basicConfig(format="%(message)s", level=logging.INFO, stream=sys.stdout)
    logger = logging.getLogger("aliasing")
    logger.info('Using output prefix %r' % args.output)

    # Define the pixel response
    pix = galsim.Pixel(args.pixel_scale)

    # Define the psf to use
    psf = galsim.Moffat(beta = args.psf_beta, fwhm = args.psf_fwhm)

    # Create an empty image that represents the whole field
    field = galsim.ImageD(args.width,args.height)
    
    # Calculate the corners of the image in arcsecs
    RAmin = (args.x_center - 0.5*args.width)*args.pixel_scale
    RAmax = (args.x_center + 0.5*args.width)*args.pixel_scale
    DECmin = (args.y_center - 0.5*args.height)*args.pixel_scale
    DECmax = (args.y_center + 0.5*args.height)*args.pixel_scale
    
    # Calculate margin size in arcsecs
    margin = args.margin*arcmin2arcsec

    # Initialize finite difference calculations if necessary
    if args.partials:
        if args.partials_order < 1 or args.partials_order > 4:
            logger.error('Bad parameter: partials-order must be an integer 1-4.')
            sys.exit(-1)
        # Initialize the finite difference coefficients to use
        if args.partials_order == 1:
            fdCoefs = (1./2.,)
        elif args.partials_order == 2:
            fdCoefs = (2./3.,-1./12.)
        elif args.partials_order == 3:
            fdCoefs = (3./4.,-3./20.,1./60.)
        else:
            fdCoefs = (4./5.,-1./5.,4./105.,-1./280.)

    # Open the source input catalog to use and read the header line
    cat = open(args.input)
    cathdr = cat.readline().split()
    logger.info('Reading input catalog %r with fields:\n%s' % (args.input,','.join(cathdr)))
    
    # Initialize the list of per-object stamp HDUs we will fill
    hdu = pyfits.PrimaryHDU()
    hduList = pyfits.HDUList([hdu])

    # surface brightness isophote to cut at in ADU units per pixel where, in the case of an
    # image stack, ADU is an average rather than a sum so that the sky decreases with stacking.
    fcut = 2.0
    f0 = fcut/(args.pixel_scale*args.pixel_scale)

    # calculate r0 from fwhm
    r0psf = 0.5*args.psf_fwhm/math.sqrt(math.pow(2.,1./args.psf_beta)-1)
    cpsf = math.pi*f0*r0psf*r0psf/(args.psf_beta-1.)

    # Loop over catalog entries
    nkeep = lineno = 0
    for line in cat:
        lineno += 1

        # position on the sky in arcsecs
        cols = line.split()
        RA = float(cols[1])*deg2arcsec
        DEC = float(cols[2])*deg2arcsec
        
        # skip sources outside our margins
        if RA < RAmin-margin or RA > RAmax+margin or DEC < DECmin-margin or DEC > DECmax+margin:
            continue
        
        # Calculate total flux in ADU units
        r_ab = float(cols[22]) # AB magnitude in r band
        i_ab = float(cols[23]) # AB magnitude in i band
        flux = args.flux_norm*math.pow(10,24-i_ab)
        # Ignore objects whose total flux is below half of our per-pixel threshold
        if flux < 0.5*fcut:
            continue
        
        # disk components
        hlr_d = float(cols[7]) # in arcsecs
        if hlr_d <= 0:
            continue
        pa_d = float(cols[9]) # position angle in degrees
        a_d = float(cols[17]) # major axis length in arcsecs
        b_d = float(cols[19]) # minor axis length in arcsecs
        # Calculate sheared ellipse aspect ratio
        q_d = b_d/a_d # between 0.2 and 1
        # Convert position angle from degrees to radians
        pa_d = pa_d*deg2rad
        
        # Convert half-light radius of exponential profile to scale radius in arcsecs
        r_scale = hlr_d/1.67835
        # Calculate shear affine transform parameters
        g = (1-q_d)/(1+q_d)
        gp = g*math.cos(2*pa_d)
        gx = g*math.sin(2*pa_d)
        detM = 1 - gp*gp - gx*gx
        # Calculate the bounding box for the limiting isophote with no psf
        x = twopi*r_scale*r_scale*f0/(flux*detM)
        rcut = -r_scale*math.log(x)
        if rcut <= 0:
            # object is below our threshold without any psf
            continue
        width = rcut*math.sqrt(((1+gp)*(1+gp)+gx*gx)/detM) # half width in arcsecs
        height = rcut*math.sqrt(((1-gp)*(1-gp)+gx*gx)/detM) # half height in arcsecs
        # Calculate the psf padding
        arg = math.pow(cpsf/flux,-1./args.psf_beta) - 1
        if arg > 0:
            rpad = r0psf*math.sqrt(arg)
        else:
            rpad = 0
        width += rpad
        height += rpad

        # Scale flux to number of vists (extra factor of 2 because 1 visit = 2 exposures)
        flux = 2*args.nvisits*flux
        
        # Calculate the offsets of this source from our image's bottom left corner in pixels
        # (which might be negative, or byeond our image bounds)
        xoffset = (RA - RAmin)/args.pixel_scale
        yoffset = (DEC - DECmin)/args.pixel_scale
        
        # Calculate the coordinates of the image pixel that contains the source center
        # (using the convention that the bottom left corner pixel has coordinates 1,1)
        xpixels = int(math.ceil(xoffset))
        ypixels = int(math.ceil(yoffset))

        # Calculate the stamp size to use as width = 2*xhalf+1 and height = 2*yhalf+1.
        # We always round up to an odd integer so that flux is consistently centered
        # (see Issue #380).
        xhalf = int(math.ceil(width/args.pixel_scale))
        yhalf = int(math.ceil(height/args.pixel_scale))

        # Build this source's stamp bounding box
        bbox = galsim.BoundsI(xpixels-xhalf,xpixels+xhalf,ypixels-yhalf,ypixels+yhalf)
        
        # Does this source overlap the image?
        if (bbox & field.bounds).area() == 0:
            continue

        # If we get this far, we are definitely keeping this source
        nkeep += 1
        logger.info('rendering stamp %d (line %d) with w x h = %d x %d' %
            (nkeep,lineno,2*xhalf+1,2*yhalf+1))

        # Calculate the subpixel shift in arcsecs (not pixels!) of the source center
        # relative to the center of pixel (xpixels,ypixels)
        xshift = (xoffset - (xpixels-0.5))*args.pixel_scale
        yshift = (yoffset - (ypixels-0.5))*args.pixel_scale
        
        # Define the nominal source parameters for rendering this object within its stamp
        params = {
            'flux':flux, 'xc':xshift, 'yc':yshift,
            'hlr':hlr_d, 'q':q_d, 'beta':pa_d,
            'g1':args.g1, 'g2': args.g2
        }

        # Create stamps for the galaxy with and w/o the psf applied
        gal = createSource(**params)
        nopsf = createStamp(gal,None,pix,bbox)
        nominal = createStamp(gal,psf,pix,bbox)

        # Add the nominal galaxy to the full field image
        overlap = nominal.bounds & field.bounds
        field[overlap] += nominal[overlap]
        
        # Initialize the datacube of stamps that we will save for this object
        datacube = [ nopsf, nominal ]

        if args.partials:
            # Specify the amount to vary each parameter for partial derivatives
            # (we don't use a dictionary here since we want to control the order)
            variations = [
                ('xc',args.pixel_scale/3.), ('yc',args.pixel_scale/3.),
                ('hlr',0.05*hlr_d),
                ('g1',0.03), ('g2',0.03)
            ]
            # loop over source parameters to vary
            for (pname,delta) in variations:
                # create stamps for each variation of this parameter
                newparams = params.copy()
                partial = galsim.ImageD(bbox)
                for step in range(args.partials_order):
                    # create and save the positive variation stamp
                    newparams[pname] = params[pname] + (step+1)*delta
                    newsource = createSource(**newparams)
                    plus = createStamp(newsource,psf,pix,bbox)
                    # create and save the negative variation stamp
                    newparams[pname] = params[pname] - (step+1)*delta
                    newsource = createSource(**newparams)
                    minus = createStamp(newsource,psf,pix,bbox)
                    # update the finite difference calculation of this partial
                    partial += (fdCoefs[step]/delta)*(plus - minus)
                # append this partial to our datacube
                datacube.append(partial)

        # Add a new HDU with a datacube for this object's stamps
        # We don't use compression = 'gzip_tile' for now since it is lossy
        # and mathematica cannot Import it.
        galsim.fits.writeCube(datacube, hdu_list = hduList)

    # Write the full field image to a separate file
    outname = args.output + '_field.fits'
    logger.info('Saving full field to %r' % outname)
    galsim.fits.write(field,outname)

    # Write out the full field image with noise added
    if args.sky_level > 0:
        rng = galsim.BaseDeviate(123)
        noise = galsim.PoissonNoise(rng,sky_level = 2*args.nvisits*args.sky_level)
        field.addNoise(noise)
        outname = args.output + '_noise.fits'
        logger.info('Saving full field to %r' % outname)
        galsim.fits.write(field,outname)

    # Write the object stamp datacubes
    outname = args.output + '_stamps.fits'
    logger.info('Saving stamps to %r' % outname)
    galsim.fits.write_file(outname, hdus = hduList, clobber = True,
        file_compress = None, pyfits_compress = None)

if __name__ == "__main__":
    main()
