#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# %load_ext autoreload
# %autoreload 2

# System modules
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.coordinates import get_sun, get_moon
from astropy.time import Time
import astropy.units as u
import numpy as np
import json

# Our modules
from reduction import get_fits_header, is_number

class observatory():

    def __init__(self,filename=None):
        '''
        Set default parameters.
        '''
        # No default filename, header or instrument
        self._filename = None
        self.header = None
        self.instrument = None
        self.params = None

        with open('instruments.json') as json_file:
            self.instruments = json.load(json_file)

    @property
    def filename(self):
        '''Laboratory image file name'''
        return self._filename

    @filename.setter # On new file, update data
    def filename(self, value):
        self.header = get_fits_header(value)
        self._filename = value
        if 'INSTRUME' in self.header:
            self.instrument = self.header['INSTRUME']
        else:
            self.instrument = 'default'
        self.params = self.instruments[self.instrument]
        self.exptime = self.header[self.params['exptime']]

    def times(self):
        pass


    def target(self):
        if 'OBJECT' in self.header:
            target = self.header['OBJECT']
        else:
            target = None
        return SkyCoord.from_name(target)


    def coordinates(self):
        value=self.params
        if not value:
            pass # List is empty
        else:
            if value['ra'] and value['dec']:
                ra  = self.header[value['ra']]
                dec = self.header[value['dec']]

                if is_number(ra):
                    #example dfosc: 14.32572
                    skycoord = SkyCoord(ra=ra, dec=dec,
                                 unit=(u.deg, u.deg))
                else:
                    #example mexman: 18:56:10.8
                    skycoord = SkyCoord(ra=ra, dec=dec,
                                 unit=(u.hourangle, u.deg))
            elif 'OBJECT' in self.header:
                target = self.header['OBJECT']
                skycoord = SkyCoord.from_name(target)
            else:
                #example oarpaf: None
                pass
        return skycoord


    def location(self):
        value=self.params
        if not value:
            pass # List is empty
        else:
            if ('LATITUDE' in self.header) \
           and ('LONGITUD' in self.header) \
           and ('ALTITUDE' in self.header):
                lat = self.header[value['location'][0]]
                lon = self.header[value['location'][1]]
                alt = self.header[value['location'][2]]
            else:
                lat = value['location'][0]
                lon = value['location'][1]
                alt = value['location'][2]

        if is_number(lat):
            earthlocation = EarthLocation(lat=lat*u.deg,
                                          lon=lon*u.deg,
                                          height=alt*u.m)
            
        else:
            earthlocation = EarthLocation(lat=lat*u.deg,
                                      lon=lon*u.deg,
                                      height=alt*u.m)

        return earthlocation

            #if ('OBSERVAT' in self.header):
            #    earthlocation = EarthLocation.of_site(self.header('OBSERVAT'))
            #   earthlocation = EarthLocation.of_address("")


    def times(self):
        value=self.params
        if not value:
            pass # List is empty
        else:
            timekey = self.header[value['obstime']]
            if 'MJD' in value['obstime']:
                obstime = Time(timekey, format='mjd')
            elif value['obstime'] == 'JD':
                obstime = Time(timekey, format='jd')
            elif 'DATE' in value['obstime']:
                obstime = Time(timekey)
            elif isinstance(value['obstime'], list):
                obstime = Time(Time(timekey[0]).unix+timekey[1])
            else:
                pass
            
        return obstime


    def detector(self):

        if ('CCDXBIN' in self.header) and ('CCDYBIN' in self.header):
            binning = [self.header['CCDXBIN'],
                       self.header['CCDXBIN']]
        elif 'CCDSUM' in self.header:
            binning = list(map(int, self.header['CCDSUM'].split(' ')))

        elif ('XBINNING' in self.header) and ('YBINNING' in self.header):
            binning = [self.header['XBINNING'],
                       self.header['YBINNING']]
        else:
            binning = [1, 1]

        return binning


    def altaz(self):
        observing_location = self.location()
        observing_time = self.times()
        aa = AltAz(location=observing_location, obstime=observing_time)
        
        object_radec = self.coordinates()
        object_altaz = object_radec.transform_to(aa)
        
        zdist = object_altaz.zen    # only in dfosc
        airmass = object_altaz.secz # only in mexman

        sun_radec = get_sun(observing_time)
        sun_altaz = sun_radec.transform_to(aa)
    
        moon_radec = get_moon(observing_time)
        moon_altaz = moon_radec.transform_to(aa)

        return aa


    def meteo(self):
        temperature = None  # 20*u.Celsius
        humidity = None # 0-1
        pressure = None    # 1000*u.hpa
        wavelength = None  # 550*u.nm
        if ('XTEMP' in self.header):
            temperature = self.header['XTEMP']*u.Celsius
        if ('HUMIDITY' in self.header):
            humidity = self.header['HUMIDITY']/100
        if ('ATMOSBAR' in self.header):
            pressure = self.header['ATMOSBAR']*u.mbar
        

    def config(self, filename=None):
        if filename is not None:
            self.filename = filename
        self.coordinates()
        self.location()
        self.times()
        self.detector()
        self.altaz()
        self.meteo()

        
    # # json array
    # [item for item in j if item.get('id')=='Mexman'

    # # json object
    # j['Mexman']




# Mettere tutto il JSON in un oggetto Python per poter trattare i dati come credi
class payload(object):
    def __init__(self, data):
        self.__dict__ = json.loads(data)


# def fill_header(filename):

#     observing_location = EarthLocation(lat=41.3*u.deg,
#                                        lon=-74*u.deg,
#                                        height=100*u.m)

#     observing_time = Time('2017-02-05 20:12:18')
#     aa = AltAz(location=observing_location, obstime=observing_time)

#     obj_radec = SkyCoord('4h42m', '-38d6m50.8s')
#     obj_altaz = object_radec.transform_to(aa)

#     temperature = None # 20*u.Celsius
#     pressure = None    # 1000*u.hpa
#     humidity = None    # 0.2
#     wavelength = None  # 550*u.nm

#     zdist = object_altaz.zen # only in dfosc
#     airmass = object_altaz.secz # only in mexman

#     sun_radec = get_sun(observing_time)
#     sun_altaz = sun_radec.transform_to(aa)

#     moon_radec = get_moon(observing_time)
#     moon_altaz = moon_radec.transform_to(aa)


def main():
    '''
    Main function
    '''
    pattern = sys.argv[1:] # "1:" stands for "From 1 on".
    show(pattern)


if __name__ == '__main__':
    '''
    If called as a script
    '''
    import sys

    if len(sys.argv) < 2 :
        print("Usage:  "+sys.argv[0]+" <Parameters>")
        sys.exit()

    main()

