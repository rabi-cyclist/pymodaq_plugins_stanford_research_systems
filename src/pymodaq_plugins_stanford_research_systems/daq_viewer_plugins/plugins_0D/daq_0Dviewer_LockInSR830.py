from typing import List
from time import perf_counter
from qtpy.QtCore import QThread
import numpy as np
from pymodaq.utils.daq_utils import ThreadCommand
from pymodaq.utils.data import DataFromPlugins, DataToExport
from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.parameter import Parameter

from pymeasure.instruments.srs import SR830
from pyvisa import ResourceManager

VISA_rm = ResourceManager()
devices = list(VISA_rm.list_resources())
device = ''
for dev in devices:
    if 'GPIB' in dev:
        device = dev
        break

interfaces = ['RS-232','GPIB']
baud_rates = [300, 1200, 2400, 4800, 9600, 19200]


class DAQ_0DViewer_LockInSR830(DAQ_Viewer_base):
    """ Instrument plugin class for a OD viewer.
    
    This object inherits all functionalities to communicate with PyMoDAQ’s DAQ_Viewer module through inheritance via
    DAQ_Viewer_base. It makes a bridge between the DAQ_Viewer module and the Python wrapper of a particular instrument.

    Attributes:
    -----------
    controller: object
        The particular object that allow the communication with the hardware, in general a python wrapper around the
         hardware library.

    """
    channels = ['X', 'Y', 'R', 'Theta', 'Aux In 1',
                'Aux In 2', 'Aux In 3', 'Aux In 4', 'Frequency', 'CH1', 'CH2']

    params = comon_parameters + [
        {'title': 'Interface', 'name': 'interface', 'type': 'list', 'limits': interfaces, 'value': interfaces[0]},
        {'title': 'VISA:', 'name': 'device', 'type': 'list', 'limits': devices, 'value': device},
        {'title': 'Baud rate (RS-232)', 'name': 'baud_rate', 'type': 'list', 'limits': baud_rates, 'value': baud_rates[4]},
        {'title': 'ID:', 'name': 'id', 'type': 'str', 'value': ""},
        {'title': 'Acquisition:', 'name': 'acq', 'type': 'group', 'children': [
            {'title': 'Use Trigger:', 'name': 'trigger', 'type': 'bool', 'value': False},
            {'title': 'Channels in separate viewer:', 'name': 'separate_viewers', 'type': 'bool', 'value': True},
            {'title': 'Channels:', 'name': 'channels', 'type': 'itemselect',
             'value': dict(all_items=channels, selected=['CH1', 'CH2'])},
            {'title': 'Sampling (Hz):', 'name': 'sampling_rate', 'type': 'list', 'limits': SR830.SAMPLE_FREQUENCIES},
            ]},
        {'title': 'Configuration:', 'name': 'config', 'type': 'group', 'children': [
            {'title': 'Reset:', 'name': 'reset', 'type': 'bool_push', 'value': False},
            {'title': 'Setup number:', 'name': 'setup_number', 'type': 'int', 'value': 1, 'min': 1, 'max': 9},
            {'title': 'Save setup:', 'name': 'save_setup', 'type': 'bool_push', 'value': False,
             'label': 'Save'},
            {'title': 'Load setup:', 'name': 'load_setup', 'type': 'bool_push', 'value': False,
             'label': 'Load'},
        ]},
    ]

    def ini_attributes(self):
        self.controller: SR830 = None

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'load_setup':
            self.controller.load_setup(self.settings['config', 'setup_number'])
            param.setValue(False)

        elif param.name() == 'save_setup':
            self.controller.save_setup(self.settings['config', 'setup_number'])
            param.setValue(False)

        elif param.name() == 'channels':
            selected_channels = param.value()['selected']
            data_list_array = [np.array([0.]) for _ in range(len(selected_channels))]
            dwas = self.create_dwas(data_list_array)
            self.dte_signal.emit(DataToExport(name='SR830', data=dwas))

        elif param.name() == 'reset':
            self.controller.reset()
            param.setValue(False)

        elif param.name() == 'trigger':
            self.controller.aquireOnTrigger(param.value())

        elif param.name() == 'sampling_rate':
            self.controller.sample_frequency = param.value()
            param.setValue(self.controller.sample_frequency)  # check it

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """

        if self.settings['controller_status'] == "Slave":
            if controller is None:
                raise Exception('no controller has been defined externally while this axe is a slave one')
            else:
                controller = controller
        else:  # Master stage
            if self.settings['interface'] == "RS-232":
                controller = SR830(self.settings['device'], baud_rate=self.settings['baud_rate'], read_termination="\r", write_termination="\r")
            else:
                controller = SR830(self.settings['device'], read_termination="\r", write_termination="\r")
        self.controller = controller

        self.controller.reset_buffer()
        self.controller.start_buffer(False)

        self.settings.child('acq', 'sampling_rate').setValue(self.controller.sample_frequency)
        info = self.controller.id
        self.settings.child('id').setValue(info)
        initialized = True
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        if self.controller is not None:
            self.controller.clear()
            self.controller.shutdown()

    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """

        selected_channels = self.settings['acq', 'channels']['selected']

        if Naverage == 1:
            snapped_list = self.controller.snap(*selected_channels)[:len(selected_channels)]
        elif Naverage > 1:
            snapped_list = self.controller.buffer_measure(Naverage=Naverage)[:2*len(selected_channels):2]
            
        data_list_array = [np.array([snapped]) for snapped in snapped_list]
        dwas = self.create_dwas(data_list_array)
        
        self.dte_signal.emit(DataToExport(name='SR830', data=dwas))

    def create_dwas(self, data_list_array: List[np.ndarray]) -> List[DataFromPlugins]:
        """ Create a list of DataFromPlugins according to the selected channels

        Parameters
        ----------
        data_list_array: List[np.ndarray]
            The list of numpy ndarray to put into a list of DataFromPlugins

        Returns
        -------
        List[DataFromPlugins]
        """
        selected_channels = self.settings['acq', 'channels']['selected']
        if self.settings['acq', 'separate_viewers']:

            dwas = [DataFromPlugins(f'SR830:{selected_channels[ind]}',
                                   data=[array],
                                   labels=[selected_channels[ind]]) for ind, array in enumerate(data_list_array)]
        else:
            dwas = [DataFromPlugins('SR830',
                                    data=data_list_array,
                                    labels=selected_channels)]
        return dwas

    def stop(self):
        """Stop the current grab hardware wise if necessary"""
        return ''


if __name__ == '__main__':
    main(__file__, init=False)
