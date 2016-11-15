#!/usr/bin/env python
# -*- coding: utf-8 -*-

################################################################################
#
# caos-collector - CAOS collector
#
# Copyright © 2016 INFN - Istituto Nazionale di Fisica Nucleare (Italy)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# Author: Fabrizio Chiarello <fabrizio.chiarello@pd.infn.it>
#
################################################################################

import argparse
import datetime
import sys
import signal


from _version import __version__
import caos_api
import ceilometer
import cfg
import log
import utils


log.setup_logger()
logger = log.get_logger()
logger.info("Logger setup.")


DEFAULT_CFG_FILE = '/etc/caos/collector.conf'


# CLI ARGs
parser = argparse.ArgumentParser(description='Data collector for CAOS.',
                                 add_help=True)

parser.add_argument('-v', '--version', action='version',
                    version='%(prog)s {version}'.format(version=__version__))

parser.add_argument('-c', '--config',
                    dest='cfg_file', metavar='FILE',
                    default=DEFAULT_CFG_FILE,
                    help='configuration file')

parser.add_argument('-f', '--force',
                    action='store_const',
                    const=True,
                    help='Enable overwriting existing samples.')

subparsers = parser.add_subparsers(dest="cmd",
                                   help='sub commands')

parser_run = subparsers.add_parser('run', help='run scheduled collection')

parser_shot = subparsers.add_parser('shot', help='shot collection')

parser_shot.add_argument('-s', '--start',
                         dest='start', metavar='TIMESTAMP',
                         nargs='?',
                         default=utils.format_date(datetime.datetime.utcnow()),
                         help='Perform shot collection from TIMESTAMP (default to now)')

parser_shot.add_argument('-r', '--repeat',
                         dest='repeat', metavar='N',
                         nargs='?',
                         default=1,
                         help='Repeat N times (default to 1)')

parser_shot.add_argument('-P', '--project',
                         dest='project', metavar='PROJECT',
                         nargs='?',
                         default='ALL',
                         help='Collect only project PROJECT (default to ALL)')

parser_shot.add_argument('-m', '--metric',
                         dest='metric', metavar='METRIC',
                         nargs='?',
                         default='ALL',
                         help='Collect only metric METRIC (default to ALL)')

parser_shot.add_argument('-p', '--period',
                         dest='period', metavar='PERIOD',
                         nargs='?',
                         default='ALL',
                         help='Collect only period PERIOD (default to ALL)')

from collector import refresh_token
from collector import setup_scheduler
from collector import run_shot

def main():
    args = parser.parse_args()
    cfg_file = args.cfg_file
    cfg.read(cfg_file)
    cfg.dump()
    log.setup_file_handlers()

    caos_api.initialize(cfg.CAOS_API_URL)
    try:
        logger.info("Checking API connectivity...")
        status = caos_api.status()
        logger.info("API version %s is in status '%s'", status['version'], status['status'])
    except caos_api.ConnectionError as e:
        logger.error("Cannot connect to API. Exiting....")
        sys.exit(1)

    try:
        logger.info("Checking API auth...")
        ok = refresh_token()
        if not ok:
            logger.error("Cannot authenticate to API: %s. Exiting...")
            sys.exit(1)
    except caos_api.AuthError as e:
        logger.error("Cannot authenticate to API: %s. Exiting...", e)
        sys.exit(1)


    cfg.CFG['force'] = None
    force = args.force
    if force:
        logger.info("FORCE COLLECTION ENABLED")
        logger.warn("FORCE WILL OVERWRITE EXISTING DATA!!!!")
        answer = raw_input("Are you sure? Type YES (uppercase) to go on: ")
        if not answer == "YES":
            return
        else:
            cfg.CFG['force'] = force

    try:
        ceilometer.initialize(cfg.CEILOMETER_MONGODB, cfg.CEILOMETER_MONGODB_CONNECTION_TIMEOUT)
    except ceilometer.ConnectionError as e:
        logger.error("Error: %s. Check your mongodb setup. Exiting...", e)
        sys.exit(1)

    cfg.CFG['shot'] = None
    cmd = args.cmd
    if cmd == 'shot':
        run_shot(args)
        sys.exit(0)
    assert(cmd != 'shot')

    assert(cmd == 'run')

    periods = cfg.PERIODS
    scheduler = setup_scheduler(periods=periods)

    def sigterm_handler(_signo, _stack_frame):
        # Raises SystemExit(0):
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)

    # this is blocking
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info('Got SIGTERM! Terminating...')
        scheduler.shutdown(wait=False)
