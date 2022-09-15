from __future__ import annotations

import logging
from itertools import zip_longest
from typing import Callable, ClassVar, List, Optional

from qtpy import QtWidgets
from qtpy.QtCore import QPoint, Qt
from qtpy.QtCore import Signal as QSignal
from qtpy.QtGui import QClipboard, QGuiApplication
from qtpy.QtWidgets import QInputDialog, QMenu, QWidget

from atef import util
from atef.check import Comparison, Equals, Range
from atef.qt_helpers import QDataclassList
from atef.widgets.core import DesignerDisplay
from atef.widgets.happi import HappiDeviceComponentWidget
from atef.widgets.ophyd import OphydAttributeData, OphydAttributeDataSummary

logger = logging.getLogger(__name__)


class StringListWithDialog(DesignerDisplay, QWidget):
    """
    A widget used to modify the str variant of QDataclassList, tied to a
    specific dialog that helps with selection of strings.

    The ``item_add_request`` signal must be hooked into with the
    caller-specific dialog tool.  This class may be subclassed to add this
    functionality.

    Parameters
    ----------
    data_list : QDataclassList
        The dataclass list to edit using this widget.

    allow_duplicates : bool, optional
        Allow duplicate entries in the list.  Defaults to False.
    """
    filename: ClassVar[str] = "string_list_with_dialog.ui"
    item_add_request: ClassVar[QSignal] = QSignal()
    item_edit_request: ClassVar[QSignal] = QSignal(list)  # List[str]

    button_add: QtWidgets.QToolButton
    button_layout: QtWidgets.QVBoxLayout
    button_remove: QtWidgets.QToolButton
    list_strings: QtWidgets.QListWidget

    def __init__(
        self,
        data_list: QDataclassList,
        allow_duplicates: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.data_list = data_list
        self.allow_duplicates = allow_duplicates
        self._setup_ui()

    def _setup_ui(self):
        starting_list = self.data_list.get()
        for starting_value in starting_list or []:
            self._add_item(starting_value, init=True)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # def test():
        #     text, success = QtWidgets.QInputDialog.getText(
        #         self, "Device name", "Device name?"
        #     )
        #     if success:
        #         self.add_items([item for item in text.strip().split() if item])

        self.button_add.clicked.connect(self.item_add_request.emit)
        self.button_remove.clicked.connect(self._remove_item_request)

        def _edit_item_request():
            self.item_edit_request.emit(self.selected_items_text)

        self.list_strings.doubleClicked.connect(_edit_item_request)

    def _add_item(self, item: str, *, init: bool = False):
        """
        Add an item to the QListWidget and the bridge (if init is not set).

        Parameters
        ----------
        item : str
            The item to add.

        init : bool, optional
            Whether or not this is the initial initialization of this widget.
            This will be set to True in __init__ so that we don't mutate
            the underlying dataclass. False, the default, means that we're
            adding a new dataclass to the list, which means we should
            definitely append it.
        """
        if not init:
            if not self.allow_duplicates and item in self.data_list.get():
                return

            self.data_list.append(item)

        self.list_strings.addItem(QtWidgets.QListWidgetItem(item))

    def add_items(self, items: List[str]) -> None:
        """
        Add one or more strings to the QListWidget and the bridge.

        Parameters
        ----------
        item : list of str
            The item(s) to add.
        """
        for item in items:
            self._add_item(item)

    @property
    def selected_items_text(self) -> List[str]:
        """
        The text of item(s) currently selected in the QListWidget.

        Returns
        -------
        selected : list of str
        """
        return [item.text() for item in list(self.list_strings.selectedItems())]

    def _remove_item_request(self):
        """Qt hook: user requested item removal."""
        for item in self.list_strings.selectedItems():
            self.data_list.remove_value(item.text())
            self.list_strings.takeItem(self.list_strings.row(item))

    def _remove_item(self, item: str) -> None:
        """
        Remove an item from the QListWidget and the bridge.

        Parameters
        ----------
        items : str
            The item to remove.
        """
        self.data_list.remove_value(item)
        for row in range(self.list_strings.count()):
            if self.list_strings.item(row).text() == item:
                self.list_strings.takeItem(row)
                return

    def remove_items(self, items: List[str]) -> None:
        """
        Remove items from the QListWidget and the bridge.

        Parameters
        ----------
        items : list of str
            The items to remove.
        """
        for item in items:
            self._remove_item(item)

    def _edit_item(self, old: str, new: str) -> None:
        """
        Edit an item in place in the QListWidget and the bridge.

        If we don't allow duplicates and new already exists, we
        need to remove old instead.

        Parameters
        ----------
        old : str
            The original item to replace
        new : str
            The new item to replace it with
        """
        if old == new:
            return
        if not self.allow_duplicates and new in self.data_list.get():
            return self._remove_item(old)
        self.data_list.put_to_index(
            index=self.data_list.get().index(old),
            new_value=new,
        )
        for row in range(self.list_strings.count()):
            if self.list_strings.item(row).text() == old:
                self.list_strings.item(row).setText(new)
                return

    def edit_items(self, old_items: List[str], new_items: List[str]) -> None:
        """
        Best-effort edit of items in place in the QListWidget and the bridge.

        The goal is to replace each instance of old with each instance of
        new, in order.
        """
        # Ignore items that exist in both lists
        old_uniques = [item for item in old_items if item not in new_items]
        new_uniques = [item for item in new_items if item not in old_items]
        # Remove items from new if duplicates aren't allowed and they exist
        if not self.allow_duplicates:
            new_uniques = [
                item for item in new_uniques if item not in self.data_list.get()
            ]
        # Add, remove, edit in place as necessary
        # This will edit everything in place if the lists are equal length
        # If old_uniques is longer, we'll remove when we exhaust new_uniques
        # If new_uniques is longer, we'll add when we exhaust old_uniques
        # TODO find a way to add these at the selected index
        for old, new in zip_longest(old_uniques, new_uniques, fillvalue=None):
            if old is None:
                self._add_item(new)
            elif new is None:
                self._remove_item(old)
            else:
                self._edit_item(old, new)

    def _show_context_menu(self, pos: QPoint):
        """
        Displays a context menu that provides copy & remove actions
        to the user

        Parameters
        ----------
        pos : QPoint
            Position to display the menu at
        """
        if len(self.list_strings.selectedItems()) <= 0:
            return

        menu = QMenu(self)

        def copy_selected():
            items = self.list_strings.selectedItems()
            text = '\n'.join([x.text() for x in items])
            if len(text) > 0:
                QGuiApplication.clipboard().setText(text, QClipboard.Mode.Clipboard)

        copy = menu.addAction('&Copy')
        copy.triggered.connect(copy_selected)

        remove = menu.addAction('&Remove')
        remove.triggered.connect(self._remove_item_request)

        menu.exec(self.mapToGlobal(pos))


class DeviceListWidget(StringListWithDialog):
    """
    Device list widget, with ``HappiSearchWidget`` for adding new devices.
    """

    _search_widget: Optional[HappiDeviceComponentWidget] = None

    def _setup_ui(self):
        super()._setup_ui()
        self.item_add_request.connect(self._open_device_chooser)
        self.item_edit_request.connect(self._open_device_chooser)

    def _open_device_chooser(self, to_select: Optional[List[str]] = None):
        """
        Hook: User requested adding/editing an existing device.

        Parameters
        ----------
        to_select : list of str, optional
            If provided, the device chooser will filter for these items.
        """
        self._search_widget = HappiDeviceComponentWidget(
            client=util.get_happi_client(),
            show_device_components=False,
        )
        self._search_widget.item_search_widget.happi_items_chosen.connect(
            self.add_items
        )
        self._search_widget.show()
        self._search_widget.activateWindow()
        self._search_widget.item_search_widget.edit_filter.setText(
            util.regex_for_devices(to_select)
        )


class ComponentListWidget(StringListWithDialog):
    """
    Component list widget using a ``HappiDeviceComponentWidget``.
    """

    _search_widget: Optional[HappiDeviceComponentWidget] = None
    suggest_comparison: QSignal = QSignal(Comparison)
    get_device_list: Optional[Callable[[], List[str]]]

    def __init__(
        self,
        data_list: QDataclassList,
        get_device_list: Optional[Callable[[], List[str]]] = None,
        allow_duplicates: bool = False,
        **kwargs,
    ):
        self.get_device_list = get_device_list
        super().__init__(data_list=data_list, allow_duplicates=allow_duplicates, **kwargs)

    def _setup_ui(self):
        super()._setup_ui()
        self.item_add_request.connect(self._open_component_chooser)
        self.item_edit_request.connect(self._open_component_chooser)

    def _open_component_chooser(self, to_select: Optional[List[str]] = None):
        """
        Hook: User requested adding/editing a componen.

        Parameters
        ----------
        to_select : list of str, optional
            If provided, the device chooser will filter for these items.
        """

        widget = HappiDeviceComponentWidget(
            client=util.get_happi_client()
        )
        widget.device_widget.custom_menu_helper = self._attr_menu_helper
        self._search_widget = widget
        # widget.item_search_widget.happi_items_chosen.connect(
        #    self.add_items
        # )
        widget.show()
        widget.activateWindow()

        if self.get_device_list is not None:
            try:
                device_list = self.get_device_list()
            except Exception as ex:
                device_list = []
                logger.debug("Failed to get device list", exc_info=ex)

            widget.item_search_widget.edit_filter.setText(
                util.regex_for_devices(device_list)
            )

    def _attr_menu_helper(self, data: List[OphydAttributeData]) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu()

        summary = OphydAttributeDataSummary.from_attr_data(*data)
        short_attrs = [datum.attr.split(".")[-1] for datum in data]

        def add_attrs():
            for datum in data:
                self._add_item(datum.attr)

        def add_without():
            add_attrs()

        def add_with_equals():
            add_attrs()
            comparison = Equals(
                name=f'{"_".join(short_attrs)}_auto',
                description=f'Comparison from: {", ".join(short_attrs)}',
                value=summary.average,
            )
            self.suggest_comparison.emit(comparison)

        def add_with_range():
            add_attrs()
            comparison = Range(
                name=f'{"_".join(short_attrs)}_auto',
                description=f'Comparison from: {", ".join(short_attrs)}',
                low=summary.minimum,
                high=summary.maximum,
            )
            self.suggest_comparison.emit(comparison)

        menu.addSection("Add all selected")
        add_without_action = menu.addAction("Add selected without comparison")
        add_without_action.triggered.connect(add_without)

        if summary.average is not None:
            add_with_equals_action = menu.addAction(
                f"Add selected with Equals comparison (={summary.average})"
            )
            add_with_equals_action.triggered.connect(add_with_equals)

        if summary.minimum is not None:
            add_with_range_action = menu.addAction(
                f"Add selected with Range comparison "
                f"[{summary.minimum}, {summary.maximum}]"
            )
            add_with_range_action.triggered.connect(add_with_range)

        menu.addSection("Add single attribute")
        for attr in data:
            def add_single_attr(*, attr_name: str = attr.attr):
                self._add_item(attr_name)

            action = menu.addAction(f"Add {attr.attr}")
            action.triggered.connect(add_single_attr)

        return menu


class BulkListWidget(StringListWithDialog):
    """
    String list widget that uses a multi-line text box for entry and edit.
    """

    def _setup_ui(self):
        super()._setup_ui()
        self.item_add_request.connect(self._open_multiline)
        self.item_edit_request.connect(self._open_multiline)

    def _open_multiline(self, to_select: Optional[List[str]] = None):
        """
        User requested adding new strings or editing existing ones.

        Parameters
        ----------
        to_select : list of str, optional
            For editing, this will contain the string items that are
            selected so that we can pre-populate the edit box
            appropriately.
        """
        to_select = to_select or []
        if to_select:
            title = 'Edit PVs Dialog'
            label = 'Add to or edit these PVs as appropriate:'
            text = '\n'.join(to_select)
        else:
            title = 'Add PVs Dialog'
            label = 'Which PVs should be included?'
            text = ''
        user_input, ok = QInputDialog.getMultiLineText(
            self, title, label, text
        )
        if not ok:
            return
        new_pvs = [pv.strip() for pv in user_input.splitlines() if pv.strip()]
        self.edit_items(to_select, new_pvs)
