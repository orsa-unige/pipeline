#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Reduction routines
'''

# System modules
from astropy import log
from astropy.io import ascii
from astropy.table import Table
import numpy as np

# Local modules
from sorters import Dfits  # apparently, no cross imports
from fits import get_fits_data, write_fits
from fill_header import init_observatory, Observatory

from naming import output_file, hist


def master_bias(filenames, keys=[]):
    generic(filenames, keys=keys, min_val=0, max_val=2000,
            method="median", product="MBIAS")


def master_dark(filenames, keys=[], mbias=None):
    generic(filenames, keys=keys, min_val=0, max_val=2000,
            method="median", product="MDARK", mbias=mbias)


def master_flat(filenames, keys=[], mbias=None, mdark=None):
    generic(filenames, keys=keys, min_val=10000, max_val=55000,
            method="median", product="MFLAT", mbias=mbias,
            mdark=mdark, normalize=True)


def correct_image(filenames, keys=[], mbias=None, mdark=None, mflat=None,
                  method='slice', new_header=False):
    generic(filenames, keys=keys, method=method, product="CLEAN",
            mbias=mbias, mdark=mdark, mflat=mflat, new_header=new_header)


def generic(filenames, keys=[], normalize=False, method=None,
            mbias=None, mdark=None, mflat=None, product=None,
            new_header=False, min_val=0, max_val=65535):

    log.info(f'fitsort {len(filenames)} filenames per {keys}')

    df = Dfits(filenames)
    sortlist = df.fitsort(keys)
    heads = df.heads

    if new_header:
        instrument = init_observatory(new_header)
        o = Observatory(**instrument)

    for value in sortlist.unique_values:
        filenames = sortlist.unique_names_for(value)
        log.info(f'getting {len(filenames)} filenames for {value}')

        # Combine (and save) data per data.
        if method == "slice" or method == "individual":
            for i, filename in enumerate(filenames):

                data = get_fits_data(filename)
                output = combine(data, normalize=normalize,
                                 min_val=min_val, max_val=max_val,
                                 mbias=mbias, mdark=mdark, mflat=mflat)

                header = o.newhead(heads[i]) if new_header else heads[i]

                closing(keys, value, product, output, counter=i,
                        header=header)

        # Combine and save acting on a data cube
        else:
            datas = np.array([get_fits_data(f) for f in filenames])
            output = combine(datas, normalize=normalize, min_val=min_val,
                             max_val=max_val, method=method,
                             mbias=mbias, mdark=mdark, mflat=mflat)

            header = o.newhead(header=heads[0]) if new_header else heads[0]

            closing(keys, value, product, output, header=header)


def closing(keys, value, product, output, counter=False, header=False):

    if header:
        # header = heads[0].copy() # TODO choose head per head
        #print(type(header))
        header.add_history(hist())
        # try:
        #     header.add_history(hist())
        #     log.info("astropy fits:", hist())
        # except:
        #     log.warn("No astropy fits. trying fitsio")
        #     try:
        #         #header.write_record("HISTORY "+hist())
        #         log.info("fitsio:", hist())
        #     except:
        #         log.error("No fitsio")
            
            
    text = dict(zip(keys, value)) if keys else None
    outfile = output_file(product=product, text=text, counter=counter)
    write_fits(output, outfile, header=header, fast=False)


def counts_ok(data, size=100, min_val=0, max_val=65535):
    '''By Anna Marini.
    Divide the frame in strips of a given size.
    Return False only if the average of a strip is not between min and max_val.    
    '''
    data_split = np.array_split(data, size)
    data_split_avg = [np.mean(arr) for arr in data_split]
    is_good = True
    for avg in data_split_avg:
        if not min_val < avg < max_val:
            log.warning(f'Saturated or non linear: {avg}')
            is_good = False
            break
    return(is_good)


def combine(images, normalize=False, method=None, precision='float32',
            mbias=None, mdark=None, mflat=None, mask=False, min_val=0, max_val=65535):
    #a = Time.now()

    # Datas from pattern
    if isinstance(images, str):
        images = [images]
    if isinstance(images[0], str):
        datas = np.array([get_fits_data(i) for i in images])
    else:
        datas = images
    # Check counts
    datas = np.array([d for d in datas if counts_ok(
        d, min_val=min_val, max_val=max_val)])

    # Master datas from filename
    if isinstance(mbias, str):
        mbias = get_fits_data(mbias)
    if isinstance(mdark, str):
        mdark = get_fits_data(mdark)
    if isinstance(mflat, str):
        mflat = get_fits_data(mflat)

    # Cannot cast type
    if mbias is not None and len(mbias):
        datas = (datas - mbias).astype(precision)
    if mdark is not None and len(mdark):
        datas = (datas - mdark).astype(precision)
    if mflat is not None and len(mflat):
        datas = (datas / mflat).astype(precision)

    del mbias, mdark, mflat

    # Did not find a faster method to save memory.
    if normalize:
        bottle = np.zeros(shape=datas.shape).astype(precision)
        for i, d in enumerate(datas):
            bottle[i] = d/np.mean(d).astype(precision)
        datas = bottle
        del bottle

    if method == 'average':
        combined = np.average(datas, axis=0).astype(precision)
    elif method == 'median':
        combined = np.median(datas, axis=0).astype(precision)
    else:  # cube or 1-slice cube.
        combined = np.squeeze(datas)

    log.info(
        f'{method}: {datas.shape}{datas.dtype} -> {combined.shape}{combined.dtype}')
    #log.info(f'Done in {Time.now().unix - a.unix :.1f}s')
    del datas  # Saving memory

    return combined


def update_keyword(header, key, *tup, comment=None):
    '''
    By Anna Marini
    Updates or create a keyword/value header pair of a given fits file list.
    '''
    value = tup[0].upper()
    #hist = time.isot[:-4]+" "

    if key not in header or not header[key]:
        text += "Created "+key+". "
    else:
        text += "Updated "+key+". Old value: "+header[key]+". "

    if comment is not None:
        text += comment

    header[key] = tup
    header.add_history(hist(text))

    return header


def mask(data, sigma=3, output_file=None, header=None):
    '''
    Create a bad pixel mask
    '''
    mask = sigma_clip(data, masked=True).mask.astype(int)
    if output_file:
        write_fits(mask, output_file, header=header)

    return mask


def mask_reg(data, output_file=None):
    '''
    Create a bad pixel region table
    '''

    y, x = np.where(data == True)
    p = np.repeat("point ", y.size)
    t = [p, x+1, y+1]

    table = Table(t, names=['# ', '## ', '###'])  # bleah

    if output_file:
        ascii.write(table, output_file, overwrite=True)

    return table
