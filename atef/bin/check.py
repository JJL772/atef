"""
`atef check` runs passive checkouts of devices given a configuration file.
"""

import argparse
import logging
from typing import Dict, Generator, List, Optional, Sequence, Tuple, Union

import apischema
import happi
import ophyd
import yaml

from ..check import (ConfigurationFile, DeviceConfiguration, PVConfiguration,
                     Result, Severity, check_device,
                     pv_config_to_device_config)
from ..util import ophyd_cleanup

logger = logging.getLogger(__name__)

DESCRIPTION = __doc__


def build_arg_parser(argparser=None):
    if argparser is None:
        argparser = argparse.ArgumentParser()

    argparser.description = DESCRIPTION
    argparser.formatter_class = argparse.RawTextHelpFormatter

    argparser.add_argument(
        "filename",
        type=str,
        help="Configuration filename",
    )

    argparser.add_argument(
        "--device",
        type=str,
        nargs="*",
        dest="filtered_devices",
        help="Limit checkout to the named device(s)",
    )

    return argparser


AnyConfiguration = Union[PVConfiguration, DeviceConfiguration]


def check_config_file(
    config: ConfigurationFile,
    filtered_devices: Optional[Sequence[str]] = None
) -> Generator[Tuple[ophyd.Device, AnyConfiguration, Severity, List[Result]], None, None]:
    for pv_config in config.pvs:
        if filtered_devices and pv_config.name not in filtered_devices:
            logger.debug(
                "Skipping filtered-out PV-only configuration %s", pv_config.name
            )
            continue

        dev_cls, dev_config = pv_config_to_device_config(pv_config)
        logger.debug("PV-only configuration %s -> %s", pv_config.name, dev_cls.__name__)

        dev = dev_cls(name=pv_config.name or "PVConfig")
        severity, results = check_device(dev, dev_config.checks)
        yield (dev, pv_config, severity, results)

    if not config.devices:
        return

    client = happi.Client.from_config()
    for dev_name, dev_config in config.devices.items():
        if filtered_devices and dev_name not in filtered_devices:
            logger.debug("Skipping filtered-out device %s", dev_name)
            continue

        try:
            search_result = client[dev_name]
        except KeyError:
            logger.error("Device %s not in happi database; skipping", dev_name)
            continue

        try:
            dev = search_result.get()
        except Exception as ex:
            logger.error(
                "Device %s invalid in happi database; skipping (%s: %s)",
                dev_name,
                ex.__class__.__name__,
                ex,
            )
            logger.debug(
                "Failed to instantiate device %r",
                dev_name,
                exc_info=True,
            )
            continue

        severity, results = check_device(dev, dev_config.checks)
        yield (dev, dev_config, severity, results)


def log_results(
    device: ophyd.Device,
    severity: Severity,
    config: Union[PVConfiguration, DeviceConfiguration],
    results: List[Result],
    *,
    severity_to_log_level: Optional[Dict[Severity, int]] = None,
):
    """Log check results to the module logger."""
    severity_to_log_level = severity_to_log_level or default_severity_to_log_level

    passed_or_failed = "passed" if severity <= Severity.warning else "FAILED"
    logger.info(
        "Device %s (%s) %s with severity %s",
        device.name,
        config.description or "no description",
        passed_or_failed,
        severity.name,
    )
    for result in results:
        log_level = severity_to_log_level[result.severity]
        if not logger.isEnabledFor(log_level):
            continue
        logger.log(log_level, result.reason)


default_severity_to_log_level = {
    Severity.success: logging.DEBUG,
    Severity.warning: logging.WARNING,
    Severity.error: logging.ERROR,
    Severity.internal_error: logging.ERROR,
}


def main(
    filename: str,
    filtered_devices: Optional[Sequence[str]] = None,
    *,
    cleanup: bool = True
):
    serialized_config = yaml.safe_load(open(filename))
    config = apischema.deserialize(ConfigurationFile, serialized_config)

    try:
        for dev, config, severity, results in check_config_file(
            config, filtered_devices=filtered_devices
        ):
            log_results(
                device=dev,
                config=config,
                severity=severity,
                results=results,
            )
    finally:
        if cleanup:
            ophyd_cleanup()
