#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Photometry module
'''

# System modules
from astropy import log
from astropy.coordinates import SkyCoord
from astropy.io import ascii
from astropy.stats import sigma_clipped_stats
from astropy.table import Table
from astropy.wcs import WCS
from astroquery.mast import Catalogs
from photutils import SkyCircularAperture, SkyCircularAnnulus, aperture_photometry
from photutils import DAOStarFinder
from photutils import make_source_mask
import astropy.units as u
import cv2
import numpy as np
#import matplotlib.pyplot as plt


try:
    import pyds9
    DISPLAY = True
except ImportError:
    log.warning("pyds9 module not found: cannot use display.")
    DISPLAY = False

# Local modules
from fits import get_fits_header, get_fits_data
from fill_header import init_observatory


def ron_gain_dark(my_instr="Mexman"):
    '''
    Get Gain, RON, Dark from config file.
    '''

    instrument = init_observatory(my_instr)
    gain = instrument['gain'] or 1
    ron = instrument['ron'] or 0
    dark_current = instrument['dark_current'] or 0
    log.info(f"Gain: {gain}, RON: {ron}, Dark current: {dark_current}")

    return ron, gain, dark_current


def detect_sources(image):
    '''
    By Anna Marini
    Extract the light sources from the image
    '''
    # threshold = detect_threshold(image, nsigma=2.)
    # sigma = 3.0 * gaussian_fwhm_to_sigma  # FWHM = 3.
    # kernel = Gaussian2DKernel(sigma, x_size=3, y_size=3)
    # kernel.normalize()

    if isinstance(image, str):
        image = get_fits_data(image)

    mask = make_source_mask(image, nsigma=2, npixels=5, dilate_size=11)
    mean, median, std = sigma_clipped_stats(image, sigma=3, mask=mask)
    daofind = DAOStarFinder(fwhm=3.0, threshold=5.*std)
    sources = daofind(image - median)
    # Pixel coordinates of the sources
    x = np.array(sources['xcentroid'])
    y = np.array(sources['ycentroid'])
    return x, y


def rescale(array):
    '''
    Take an array.  Rescale min to 0, max to 255, then change dtype,
    as opencv loves uint8 data type.  Returns the rescaled uint8 array.
    '''
    array -= np.min(array)
    array = array/(np.max(array)/255.0)
    return array.astype(np.uint8)


def detect_donuts(filename, template):
    '''
    Use opencv to find centroids of highly defocused images template matching.
    '''

    img = rescale(get_fits_data(filename))
    tpl = rescale(get_fits_data(template))

    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    threshold = 0.6

    loc = np.where(res >= threshold)
    x, y = loc
    p = np.repeat("point ", y.size)
    t = [p, (y+tpl.shape[0]/2), (x+tpl.shape[1]/2)]
    table = Table(t, names=['# ', '## ', '###'])  # bleah
    ascii.write(table, "donuts.reg", overwrite=True)

    return res


def load_catalog(filename=False, header=False, wcs=False, ra_key=False, dec_key=False):
    '''
    From Anna Marini: get positions from catalog.
    '''

    if filename and not header:
        header = get_fits_header(filename)
    if header and not wcs:
        wcs = WCS(header)
        if ra_key and dec_key:
            ra = header[ra_key]
            dec = header[dec_key]

    ra = wcs.wcs.crval[0]
    dec = wcs.wcs.crval[1]

    # Diagonal
    diag_bound = wcs.pixel_to_world_values([[0, 0], wcs.pixel_shape])
    radius = np.mean(diag_bound[1] - diag_bound[0]) / 2

    catalog = Catalogs.query_region(f'{ra} {dec}',
                                    # frame='icrs',
                                    # unit="deg",
                                    radius=radius,
                                    catalog='Gaia', version=2)

    return catalog


def set_apertures(catalog, limit=16, r=10, r_in=15.5, r_out=25):
    '''
    From Anna Marini: get a catalog and
    set apertures and annulus for photometry.
    '''
    radec = catalog['ra', 'dec', 'phot_g_mean_mag']
    mask = radec['phot_g_mean_mag'] < limit
    radec = radec[mask]

    positions = SkyCoord(radec['ra'], radec['dec'],
                         frame='fk5',
                         unit=(u.deg, u.deg))

    aperture = SkyCircularAperture(positions,
                                   r=r*u.arcsec)
    annulus = SkyCircularAnnulus(positions,
                                 r_in=r_in*u.arcsec,
                                 r_out=r_out*u.arcsec)
    apers = [aperture, annulus]

    return apers


#def do_photometry(data, apers, wcs, obstime=False, flux=False, zero_point_flux=1):
def do_photometry(data, apers, wcs, ron, gain, dark_current, obstime=False):
    '''
    Perform the aperture photometry.
    '''

    phot_table = aperture_photometry(data, apers, wcs=wcs)

    pixar = apers[0].to_pixel(wcs)
    pixan = apers[1].to_pixel(wcs)

    bkg_mean = phot_table['aperture_sum_1'] / pixan.area
    bkg_sum = bkg_mean * pixar.area
    final_sum = phot_table['aperture_sum_0'] - bkg_sum
    
    # flux_sum = phot_table['aperture_sum_0'] - bkg_sum #needed to change name, because of ambiguities due to the same name for different variables
    
    signal_noise_ratio =  final_sum / np.sqrt(final_sum
                                              + bkg_mean * pixar.area
                                              + ron
                                              + ((gain/2)**2)*pixan.area
                                              + dark_current*pixan.area)
    
    # error = signal_noise_ratio
    # final_sum = flux_sum

    # if not flux:
    #     final_sum =  -2.5*np.log10(flux_sum/ zero_point_flux) 
    #     error = (np.log10(np.e))*2.5*(error/flux_sum) 
        
    phot_table['residual_aperture_sum'] = final_sum
    phot_table['mjd-obs'] = obstime       
    phot_table['error'] = signal_noise_ratio

##    phot_table['poisson_err'] = np.sqrt(final_sum)

    #log.info(phot_table)

    return phot_table


def apphot(filenames, reference=0, display=DISPLAY, r=False, r_in=False, r_out=False):
    '''
    Perform the aperture photometry
    '''

    filenames = sorted(filenames)

    header0 = get_fits_header(filenames[reference])
    wcs0 = WCS(header0)

    catalog = load_catalog(wcs=wcs0)
    if r and r_in and r_out:
        apers = set_apertures(catalog, r=r, r_in=r_in, r_out=r_out)
    else:
        apers = set_apertures(catalog)

    tables = Table()
    err_table = Table()

    if display:
        d = pyds9.DS9("ds9")

    for filename in filenames:
        header = get_fits_header(filename)
        data = get_fits_data(filename)
        wcs = WCS(header)

        #catalog = load_catalog(wcs=wcs)
        #apers = set_apertures(catalog, r=r, r_in=r_in, r_out=r_out)

        ron, gain, dark_current = ron_gain_dark()
    
        phot_table = do_photometry(data, apers, wcs, ron, gain, dark_current, obstime=header['MJD-OBS'])
        # phot_table = do_photometry(data, apers, wcs, obstime=header['MJD-OBS'],
        #                            flux=False, zero_point_flux=1)

        # positions = SkyCoord(catalog['ra'], catalog['dec'],
        #                      frame='icrs',
        #                      unit=(u.deg, u.deg))

        if display:
            d.set(f"file {filename}")

            # for i,pos in enumerate(positions):
            #     p = pos.to_pixel(wcs)
            #     circ = f'circle({p[0]}, {p[1]}, {10})'
            #     d.set("regions", circ)
            #     d.set("region", f"text {p[0]} {p[1]} "+"{"+str(i)+"}")

            for i, aper in enumerate(apers[0].to_pixel(wcs)):
                circ = f'circle({aper.positions[0]}, {aper.positions[1]}, {aper.r})'
                d.set("regions", circ)
                d.set(
                    "region", f"text {aper.positions[0]}, {aper.positions[1]} "+"{"+str(i)+"}")

            for aper in apers[1].to_pixel(wcs):
                circ = f'circle({aper.positions[0]}, {aper.positions[1]}, {aper.r_in})'
                d.set("regions", circ)
                circ = f'circle({aper.positions[0]}, {aper.positions[1]}, {aper.r_out})'
                d.set("regions", circ)

        tables.add_column(phot_table["residual_aperture_sum"], rename_duplicate=True)
        err_table.add_column(phot_table["error"], rename_duplicate=True)
        log.info(f"Done {filename}")

    return tables, err_table


# def plot(filenames, dat_file = 'gj3470-defot.dat'):
#     filenames = sorted(filenames) 
#     tables, err_table = apphot(filenames, r=6, r_in=15.5, r_out=25)

#     t = [get_fits_header(f, fast=True)["MJD-OBS"] for f in filenames]    
#     magnitude = np.array([tables[k] for k in tables.keys()])
#     mag_err = np.array([err_table[k] for k in err_table.keys()])
#     defot_table = ascii.read(dat_file)
#     defot_time = defot_table['col2'] - 2400000 

#     m = [0, 1, 19, 14, 11]
#     defot_mags = [defot_table['col8'] - defot_table['col9'], defot_table['col8'] - defot_table['col10'],
#                   defot_table['col8'] - defot_table['col11'], defot_table['col8'] - defot_table['col12'],
#                   defot_table['col8'] - defot_table['col13']]
    
#     defot_errs = [np.sqrt(defot_table['col14']**2 + defot_table['col15']**2),
#                   np.sqrt(defot_table['col14']**2 + defot_table['col16']**2),
#                   np.sqrt(defot_table['col14']**2 + defot_table['col17']**2),
#                   np.sqrt(defot_table['col14']**2 + defot_table['col18']**2),
#                   np.sqrt(defot_table['col14']**2 + defot_table['col19']**2)]
    
#     fig = plt.figure()
#     for n in range(1,6):
#         ax = fig.add_subplot(2,3,n)
#         ax.errorbar(defot_time, defot_mags[n-1], yerr = defot_errs[n-1], fmt = ' ', elinewidth = 1,
#                     marker = 'o', markersize = 1.5)
#         ax.errorbar(t, magnitude[:,2] - magnitude[:,m[n-1]],
#                     yerr = np.sqrt(mag_err[:,2]**2 + mag_err[:,m[n-1]]**2),fmt = ' ',
#                     elinewidth = 1,
#                     marker = 'o', markersize = 1.5)

#         ax.legend(('Defot Plot', 'Apphot Plot'))
#         ax.set_xlabel('Time (MJD)')
#         ax.set_ylabel('Magnitude')

#     return(plt.show())
