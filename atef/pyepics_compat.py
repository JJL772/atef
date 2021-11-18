from __future__ import annotations

from typing import (Any, ClassVar, Dict, List, Literal, NoReturn, Optional,
                    Tuple, Union)

from ophyd._dispatch import EventDispatcher, wrap_callback
from ophyd.signal import EpicsSignalBase
from typing_extensions import Protocol


class PyepicsMonitorCallback(Protocol):
    def __call__(self, value: Any, timestamp: Any, **kwargs) -> NoReturn:
        ...


class PyepicsConnectionCallback(Protocol):
    def __call__(
        self, *, pvname: str, conn: bool, pv: PyepicsPvCompatibility
    ) -> NoReturn:
        ...


class PyepicsAccessCallback(Protocol):
    def __call__(
        self, read_access: bool, write_access: bool, *,
        pv: PyepicsPvCompatibility
    ) -> NoReturn:
        ...


PyepicsForm = Literal["time", "ctrl", "native"]


class PyepicsPvCompatibility:
    """
    epics.PV API compatibility layer, where other data sources can be used.

    Aiming for a reasonable method and attribute compatibility, though not
    everything will be perfect.
    """
    _args: Dict[str, Any]
    _dispatcher: EventDispatcher
    _reference_count: int  # used externally by EpicsSignal, ew
    _referrer: EpicsSignalBase
    _user_max_count: Optional[int]
    access_callbacks: List[PyepicsAccessCallback]
    auto_monitor: Optional[Union[int, bool]]
    as_string: bool
    callbacks: Dict[int, Tuple[PyepicsMonitorCallback, dict]]
    connected: bool
    connection_callbacks: List[PyepicsConnectionCallback]
    connection_timeout: float
    form: str = PyepicsForm
    pvname: str
    verbose: bool
    _fields: ClassVar[Tuple[str, ...]] = (
        'access',
        'char_value',
        'chid',
        'count',
        'enum_strs',
        'ftype',
        'host',
        'lower_alarm_limit',
        'lower_ctrl_limit'
        'lower_disp_limit',
        'lower_warning_limit',
        'nanoseconds',
        'posixseconds',
        'precision',
        'pvname',
        'read_access',
        'severity',
        'status',
        'timestamp',
        'units',
        'upper_alarm_limit',
        'upper_ctrl_limit',
        'upper_disp_limit',
        'upper_warning_limit',
        'value',
        'write_access',
    )

    def __init__(
        self,
        pvname: str,
        callback: Optional[
            Union[PyepicsMonitorCallback, List[PyepicsMonitorCallback],
                  Tuple[PyepicsMonitorCallback, ...]]
            ] = None,
        form: PyepicsForm = "time",
        verbose: bool = False,
        auto_monitor: Optional[Union[int, bool]] = None,
        count: Optional[int] = None,
        connection_callback: Optional[PyepicsConnectionCallback] = None,
        connection_timeout: Optional[float] = None,
        access_callback: Optional[PyepicsAccessCallback] = None,
        *,
        dispatcher: EventDispatcher,
        referrer: EpicsSignalBase,
    ):
        self.pvname = pvname
        self.callbacks = {}
        self.verbose = verbose
        self.form = form
        self.auto_monitor = auto_monitor
        self._user_max_count = count
        self._args = {}.fromkeys(self._fields)
        self._args.update(
            pvname=self.pvname,
            count=count,
            nelm=-1,
            type="unknown",
            typefull="unknown",
            access="unknown",
        )
        self._dispatcher = dispatcher
        self._reference_count = 0
        self._referrer = referrer
        self.access_callbacks = []
        self.as_string = referrer.as_string
        self.callbacks = {}
        self.connected = False
        self.connection_callbacks = []
        self.connection_timeout = connection_timeout or 1.0

        if isinstance(callback, (tuple, list)):
            self.callbacks = {
                i: (wrap_callback(self._dispatcher, "monitor", cb), {})
                for i, cb in enumerate(callback)
                if callable(cb)
            }
        elif callable(callback):
            self.callbacks[0] = (
                wrap_callback(self._dispatcher, "monitor", callback),
                {}
            )

        if connection_callback is not None:
            self.connection_callbacks.append(
                wrap_callback(
                    self._dispatcher, "metadata", connection_callback
                )
            )

        if access_callback is not None:
            self.access_callbacks.append(
                wrap_callback(self._dispatcher, "metadata", access_callback)
            )

        wrap_callback(self._dispatcher, "metadata", self._make_connection)()

    def _mark_as_connected(self, connected: bool = True):
        self.connected = True
        for cb in self.connection_callbacks:
            cb(pvname=self.pvname, conn=self.connected, pv=self)

        for cb in self.access_callbacks:
            cb(True, False, pv=self)

    def _make_connection(self):
        # Subclass should reimplement me
        self._mark_as_connected()

    def run_callbacks(self):
        for index in sorted(list(self.callbacks)):
            self.run_callback(index)

    def run_callback(self, index: int):
        try:
            fcn, kwargs = self.callbacks[index]
        except KeyError:
            return

        if callable(fcn):
            kwd = self._args.copy()
            kwd.update(kwargs)
            kwd["cb_info"] = (index, self)
            fcn(**kwd)

    def add_callback(
        self, callback=None, index=None, run_now=False, with_ctrlvars=True,
        **kwargs
    ):
        if not callable(callback):
            return

        callback = wrap_callback(self._dispatcher, "monitor", callback)
        if index is None:
            index = 1
            if len(self.callbacks) > 0:
                index = 1 + max(self.callbacks.keys())
        self.callbacks[index] = (callback, kwargs)

        if run_now and self.connected:
            self.run_callback(index)
        return index

    def _getarg(self, arg):
        return self._args.get(arg, None)

    def get_all_metadata_blocking(self, timeout):
        """ophyd API extension to epics.PV."""
        self.get_ctrlvars()
        md = self._args.copy()
        md.pop("value", None)
        return md

    def get_all_metadata_callback(self, callback, *, timeout):
        """ophyd API extension to epics.PV."""
        def get_metadata_thread(pvname):
            md = self.get_all_metadata_blocking(timeout=timeout)
            callback(pvname, md)

        self._dispatcher.schedule_utility_task(
            get_metadata_thread, pvname=self.pvname
        )

    def clear_callbacks(self):
        super().clear_callbacks()
        self.access_callbacks.clear()
        self.connection_callbacks.clear()

    def put(
        self,
        value,
        wait=False,
        timeout=30.0,
        use_complete=False,
        callback=None,
        callback_data=None,
    ):
        if callback:
            callback = wrap_callback(self._dispatcher, "get_put", callback)
            if isinstance(callback_data, dict):
                callback(**callback_data)
            else:
                callback(data=callback_data)

    def get_ctrlvars(self, **kwargs):
        return self._args.copy()

    def get_timevars(self, **kwargs):
        return self._args.copy()

    def get(
        self,
        count=None,
        as_string=None,
        as_numpy=True,
        timeout=None,
        with_ctrlvars=False,
        use_monitor=True,
    ):
        return self.get_with_metadata(
            count=count, as_string=as_string
        )["value"]

    def get_with_metadata(self, as_string=None, **kwargs):
        # Subclasses should update `._args` here
        raise NotImplementedError(
            "Subclasses should implement get_with_metadata"
        )

    def wait_for_connection(self, *args, **kwargs):
        self.get_with_metadata()
        return True
