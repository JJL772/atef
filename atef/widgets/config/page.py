"""
Widgets used for navigating the tree.

Page widgets should include data widgets inside of their
layouts, using bare ``QWidget`` instances as placeholders
when defined in a ui file.

They may have buttons for adding data row widgets and for
adding nodes to the tree. They are responsible for hooking up
navigation, deletion, and rearrangement controls.

Typically they will be instantiated using dataclasses that
will then be distributed to the data widgets. After instantiation
a page widget will need to be linked up to the tree using the
``link_page`` helper function.
"""
from __future__ import annotations

from typing import ClassVar, Dict, Optional, Type, Union
from weakref import WeakValueDictionary

from qtpy.QtWidgets import (QComboBox, QPushButton, QStyle, QTableWidget,
                            QToolButton, QTreeWidget, QTreeWidgetItem,
                            QVBoxLayout, QWidget)

from atef.config import (Configuration, ConfigurationGroup,
                         DeviceConfiguration, PVConfiguration,
                         ToolConfiguration)

from ..core import DesignerDisplay
from .data import (ConfigurationGroupRowWidget, ConfigurationGroupWidget,
                   NameDescTagsWidget)


def link_page(item: AtefItem, widget: PageWidget):
    """
    Link a page widget to an atef tree item.

    All linkage calls should go through here to remove ambiguity
    about ordering, etc. and so each object only has to worry about
    how to update itself.

    Parameters
    ----------
    item : AtefItem
        The tree item to link.
    widget : PageWidget
        The widget to link.
    """
    item.assign_widget(widget)
    widget.assign_tree_item(item)


class AtefItem(QTreeWidgetItem):
    """
    A QTreeWidget item with some convenience methods.

    Must be assigned a page using ``link_page``.

    Parameters
    ----------
    tree_parent : AtefItem or QTreeWidget
        The node on the tree above this node.
        Passing a QTreeWidget means that this is a top-level node.
    name : str
        The text on the left column of the tree view.
    func_name : str
        The text on the right column of the tree view.
    """
    widget: Optional[PageWidget]
    parent_tree_item: QTreeWidgetItem
    full_tree: QTreeWidget

    def __init__(
        self,
        tree_parent: Union[AtefItem, QTreeWidget],
        name: str,
        func_name: Optional[str] = None,
    ):
        super().__init__()
        self.widget = None
        self.setText(0, name)
        if func_name is not None:
            self.setText(1, func_name)
        if isinstance(tree_parent, QTreeWidget):
            self.parent_tree_item = tree_parent.invisibleRootItem()
            self.full_tree = tree_parent
        else:
            self.parent_tree_item = tree_parent
            self.full_tree = tree_parent.full_tree
        self.parent_tree_item.addChild(self)

    def assign_widget(self, widget: PageWidget) -> None:
        """
        Updates this tree item with a reference to the corresponding page.

        Parameters
        ----------
        widget : PageWidget
            The page to show when this tree item is selected.
        """
        self.widget = widget

    def find_ancestor_by_widget(self, cls: Type[QWidget]) -> Optional[AtefItem]:
        """Find an ancestor widget of the given type."""
        ancestor = self.parent_tree_item
        while hasattr(ancestor, "parent_tree_item"):
            widget = getattr(ancestor, "widget", None)
            if isinstance(widget, cls):
                return ancestor
            ancestor = ancestor.parent_tree_item

        return None

    def find_ancestor_by_item(self, cls: Type[AtefItem]) -> Optional[AtefItem]:
        """Find an ancestor widget of the given type."""
        ancestor = self.parent_tree_item
        while hasattr(ancestor, "parent_tree_item"):
            if isinstance(ancestor, cls):
                return ancestor
            ancestor = ancestor.parent_tree_item

        return None


class PageWidget(QWidget):
    """
    Base class for widgets that coorespond to a tree node.

    Contains utilities for navigating the tree and for loading
    data widgets into placeholders.

    Must be linked up to the tree using the ``link_page``
    function after being instantiated, not during.
    """
    tree_item: AtefItem
    parent_tree_item: AtefItem
    full_tree: QTreeWidget

    parent_button: Optional[QToolButton]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.parent_button = None
        self.child_button_map = WeakValueDictionary()

    def assign_tree_item(self, item: AtefItem):
        """
        Updates this page with references to the tree.

        Parameters
        ----------
        item : AtefItem
            The item that should be showing this page.
        """
        self.tree_item = item
        self.parent_tree_item = item.parent_tree_item
        self.full_tree = item.full_tree
        # Make sure we update our parent button's tooltip on tree changes
        self.full_tree.itemChanged.connect(
            self._update_parent_tooltip_from_tree,
        )

    def _update_parent_tooltip_from_tree(
        self,
        item: QTreeWidgetItem,
        **kwargs,
    ):
        """
        Update the parent tooltip if our parent's name changes.
        """
        if self.parent_button is None:
            return
        if item is self.parent_tree_item:
            self.update_parent_tooltip()

    def update_parent_tooltip(self):
        """
        Ensure that the to-parent tooltip is updated, accurate, and helpful.
        """
        if self.parent_button is None:
            return
        nav_parent = self.get_nav_parent()
        self.parent_button.setToolTip(
            "Navigate to parent item "
            f"{nav_parent.text(0)} "
            f"({nav_parent.text(1)})"
        )

    def setup_parent_button(self, button: QToolButton):
        """
        Set up a button's style and make it navigate to our parent page.

        We can only have exactly one parent button at a time.
        """
        # Retain a reference to this button for later
        self.parent_button = button
        # Make the button work
        button.clicked.connect(self.navigate_to_parent)
        # Add the appropriate symbol
        icon = self.style().standardIcon(QStyle.SP_FileDialogToParent)
        button.setIcon(icon)
        # Make sure the button's starting tooltip is correct
        self.update_parent_tooltip()

    def setup_child_button(self, button: QToolButton, item: AtefItem):
        """
        Set up a button's style and make it navigate to a specific child page.
        """
        # Create a function that navigates to the right page
        def inner_navigate(**kwargs):
            self.navigate_to(item)

        # Make the button work
        button.clicked.connect(inner_navigate)
        # Add the appropriate symbol
        icon = self.style().standardIcon(QStyle.SP_ArrowRight)
        button.setIcon(icon)
        # Make sure the tooltip is helpful
        button.setToolTip(
            f"Navigate to child {item.text(1)}"
        )

    def navigate_to(self, item: AtefItem, *args, **kwargs):
        """
        Make the tree switch to a specific item.

        This can be used to navigate to child items, for example.

        Parameters
        ----------
        item : AtefItem
            The tree node to navigate to.
        """
        self.full_tree.setCurrentItem(item)

    def navigate_to_parent(self, *args, **kwargs):
        """
        Make the tree switch to this widget's parent in the tree.
        """
        self.navigate_to(self.get_nav_parent())

    def get_nav_parent(self) -> AtefItem:
        """
        Get the navigation parent target item.

        This is self.parent_tree_item normally except when we are
        a top-level item, in which case the target should be the
        overview widget because otherwise there isn't any parent
        to navigate to.
        """
        if isinstance(self.parent_tree_item, AtefItem):
            return self.parent_tree_item
        else:
            return self.full_tree.topLevelItem(0)

    def insert_widget(self, widget: QWidget, placeholder: QWidget):
        """
        Helper function for slotting e.g. data widgets into placeholders.
        """
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        placeholder.setLayout(layout)
        placeholder.layout().addWidget(widget)


class ConfigurationGroupPage(DesignerDisplay, PageWidget):
    """
    Page that handles all components of a ConfigurationGroup.
    """
    name_desc_tags_placeholder: QWidget
    config_group_placeholder: QWidget
    config_table: QTableWidget
    add_row_button: QPushButton
    add_row_type_combo: QComboBox

    config_cls_options: ClassVar[Dict[str, Type[Configuration]]] = {
        cls.__name__: cls for cls in (
            ConfigurationGroup,
            DeviceConfiguration,
            PVConfiguration,
            ToolConfiguration,
        )
    }

    def __init__(self, data: ConfigurationGroup, **kwargs):
        super().__init__(**kwargs)
        self.data = data
        # Create the static sub-widgets and place them
        self.name_desc_tags_widget = NameDescTagsWidget(data=data)
        self.config_group_widget = ConfigurationGroupWidget(data=data)
        self.insert_widget(
            self.name_desc_tags_widget,
            self.name_desc_tags_placeholder,
        )
        self.insert_widget(
            self.config_group_widget,
            self.config_group_placeholder,
        )
        # Make sure the parent button is set up properly
        self.setup_parent_button(self.name_desc_tags_widget.parent_button)
        # Fill in the rows from the initial data
        for config in data.configs:
            self.add_config_row(config)
        # Allow the user to add more rows
        self.add_row_button.connect(self.add_config_row)
        # Fill in the row type selector box
        for option in self.config_cls_options:
            self.add_row_type_combo.addItem(option)

    def add_config_row(self, config: Optional[Configuration] = None, **kwargs):
        if config is None:
            config = self.config_cls_options[
                self.add_row_type_combo.currentText()
            ]()
        config_row = ConfigurationGroupRowWidget(data=config)
        row_count = self.config_table.rowCount()
        self.config_table.insertRow(row_count)
        self.config_table.setCellWidget(row_count, 0, config_row)
        self.config_table.setRowHeight(row_count, config_row.height())
