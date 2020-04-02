#!/usr/bin/env python
# Copyright (C) 2020 Xiphos Systems Corp.

import ctypes
import numpy as np

from queue import Queue

from picosdk.constants import PICO_STATUS
from picosdk.functions import adc2mV, assert_pico_ok
from picosdk.ps3000a import ps3000a as ps


class Picoscope:
    def __init__(self, serial=None):
        # Create chandle and status ready for use
        self.chandle = ctypes.c_int16()
        serial = ctypes.c_char_p(serial)

        # Open PicoScope 3000 Series device
        open_status = ps.ps3000aOpenUnit(ctypes.byref(self.chandle), serial)
        if self.chandle == -1:
            raise Exception('Failed to open scope')
        elif self.chandle == 0:
            raise Exception('Scope not found')
        # External power not found, switch to USB power
        if open_status == PICO_STATUS['PICO_POWER_SUPPLY_NOT_CONNECTED']:
            assert ps.ps3000aChangePowerSource(chandle, open_status) == 0, \
                    'Failed change power source'

        self.ds_mode = ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        self.ds_ratio = 1
        self.overview_buffer = np.zeros(shape=0, dtype=np.int16)
        # Buffer, not registered with the driver, to keep all captured data
        self.queue = Queue()
        self.sample_count = 0
        self.__sampling_configured = False

    @property
    def streaming_ready_cb(self):
        return self.__streaming_ready_cb

    @streaming_ready_cb.setter
    def streaming_ready_cb(self, cb):
        '''Convert the python function into a C function pointer

        :param cb: reference to a callback function
        '''
        if cb:
            self.__streaming_ready_cb = ps.StreamingReadyType(cb)
        else:
            self.__streaming_ready_cb = None

    @property
    def max_adc_count(self):
        '''Maximum ADC count reported by calls to get values.
        '''
        __max = ctypes.c_int16()
        assert_pico_ok(ps.ps3000aMaximumValue(self.chandle, ctypes.byref(__max)))
        return __max

    def set_channel(self, channel, enable=True, coupling='DC', range='2V', aoffset=0.0):
        '''Specify whether an input channel is to be enabled, its input
        coupling type, voltage range and analog offset.

        :param channel: The channel to be configured, values are: [A, B, C, D]
        :param enable: Whether or not to enable the channel, boolean
        :param coupling: The impedance and coupling type, values are:
                         - AC: 1 megohm impedance, AC coupling. The channel
                               accepts input frequencies from about 1 hertz up
                               to its maximum –3 dB analog bandwidth.
                         - DC: 1 megohm impedance, DC coupling. The scope
                               accepts all input frequencies from zero (DC) up
                               to its maximum –3 dB analog bandwidth
        :param range: The input voltage range, values are:
                      ['10MV', '20MV', '50MV', '100MV', '200MV', '500MV', '1V',
                       '2V', '5V', '10V', '20V', '50V'],
        :param aoffset: The voltage to add to the input channel before
                        digitization. The allowable range of offsets depends on
                        the input range selected for the channel, float
        '''
        assert_pico_ok(ps.ps3000aSetChannel(self.chandle,
                                    ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{channel}'],
                                    enable,
                                    ps.PS3000A_COUPLING[f'PS3000A_{coupling}'],
                                    ps.PS3000A_RANGE[f'PS3000A_{range}'],
                                    aoffset))

    def set_downsampling_parameters(self, mode, ratio=1):
        '''Initialize downsampling parameters used by set_data_buffer and
        run_streaming

        :param mode: The downsampling mode, values are:
                     - none: Default. No downsampling, return raw data values
                     - aggregate: Reduces every block of n values to just two
                                  values: a minimum and a maximum. The minimum
                                  and maximum values are returned in two
                                  separate buffers.
                     - average: Reduces every block of n values to a single
                                value representing the average (arithmetic
                                mean) of all the values.
                     - decimate: Reduces every block of n values to just the
                                 first value in the block, discarding all the
                                 other values.
        :param ratio: The downsampling factor that will be applied to
                      the raw data
        '''
        assert mode in ['none', 'aggregate', 'average', 'decimate']
        self.ds_mode = ps.PS3000A_RATIO_MODE[f'PS3000A_RATIO_MODE_{mode}']
        self.ds_ratio = ratio

    def set_data_buffer(self, channel, size, segment=0):
        '''Tell the driver where to store the data that will be returned after
        the next call to one of the GetValues. The data can be either
        unprocessed or downsampled.

        :param channel: The channel associated to the buffer, values are: [A, B, C, D]
        :param size: The size of the overview buffer. This is a temporary
                     buffer used for storing the data before returning it to
                     the application.
        :param segment: Index of the memory segment to be used.
        '''
        self.overview_buffer.resize(size)

        assert_pico_ok(ps.ps3000aSetDataBuffer(self.chandle,
                                               ps.PS3000A_CHANNEL[f'PS3000A_CHANNEL_{channel}'],
                                               self.overview_buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                                               size,
                                               segment,
                                               self.ds_mode))

    def start_sampling(self, mode, sampling_interval, time_unit,
                       pre_trig_samples=0, post_trig_samples=0,
                       auto_stop=True):
        '''Tell the oscilloscope to start collecting data in streaming mode.
        When data has been collected from the device it is downsampled if
        necessary and then delivered to the application.

        :param mode: Select picoscope sampling mode. Values are:
                     ['block', 'ets', 'rapide block', 'streaming']
        :param sampling_interval: On entry, the requested time interval between
                                  samples, in units of time_unit;
                                  on exit, the actual time interval used.
        :param time_unit: The unit of time used for sampleInterval. Values are:
                          ['fs', 'ps', 'ns', 'us', 'ms', 's']
        :param pre_trig_samples: The maximum number of raw samples before a
                                 trigger event for each enabled channel.
        :param post_trig_samples: The maximum number of raw samples after a
                                  trigger event for each enabled channel.
        :param auto_stop: A flag that specifies if the streaming should stop
                          when all of `pre_trig_samples + post_trig_samples`
                          have been captured.
        '''

        if mode in ['block', 'ets', 'rapide block']:
            raise NotImplementedError(f'sampling mode {mode} not implemented')

        if self.overview_buffer.shape == 0:
            raise Exception('Please call set_data_buffer before start_sampling')

        assert time_unit in ['fs', 'ps', 'ns', 'us', 'ms', 's']

        size = self.overview_buffer.shape[0]

        if post_trig_samples == 0:
            post_trig_samples = size * 1000

        assert_pico_ok(ps.ps3000aRunStreaming(self.chandle,
                                              ctypes.byref(sampling_interval),
                                              ps.PS3000A_TIME_UNITS[f'PS3000A_{time_unit.upper()}'],
                                              pre_trig_samples,
                                              post_trig_samples,
                                              auto_stop,
                                              self.ds_ratio,
                                              self.ds_mode,
                                              size))
        self.__sampling_configured = True

    def get_streaming_values(self, param=None):
        '''Request the next block of samples from the driver. Samples will be
        sent to self.streaming_ready_cb for processing.

        :param param: a void pointer passed to the callback
        '''
        if not self.__sampling_configured:
            raise Exception('Please call start_sampling before get_streaming_values')

        ps.ps3000aGetStreamingLatestValues(self.chandle, self.streaming_ready_cb, param)

    def __del__(self):
        # Stop scope from sampling data and close
        assert_pico_ok(ps.ps3000aStop(self.chandle))
        assert_pico_ok(ps.ps3000aCloseUnit(self.chandle))
