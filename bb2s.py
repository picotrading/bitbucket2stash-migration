#!/usr/bin/env python2

'''
Script which helps to migrate Git repos from Bitbucket to Stash.

Usage:
  bb2s [options] list bitbucket repos <bitbucket_prj>
  bb2s [options] list stash (projects|repos <stash_prj_key>)
  bb2s [options] <bitbucket_prj> <bitbucket_repo> <stash_prj_name> \
<stash_prj_key> [<stash_repo>]
  bb2s -h | --help
  bb2s --version

Options:
  -c FILE --config=FILE  Config file path [default: bb2s.ini].
  -d --debug             Show debug messages.
  -q --quiet             Do not show any messages.
  -h --help              Show this screen.
  --version              Show version.
'''

from docopt import docopt
import ConfigParser
import git
import json
import logging
import os
import requests
import shutil
import sys
import tempfile


class Bitbucket:
    # Bitbucket API:
    # https://confluence.atlassian.com/display/BITBUCKET/Use+the+Bitbucket+REST+APIs

    username = ''
    password = ''
    project = ''
    log = None

    def __init__(self, username, password, project, logger):
        self.username = username
        self.password = password
        self.project = project
        self.log = logger

        self.log.debug('Creating Bitbucket object instance')

    def get_repo_list(self, url=None):
        self.log.debug('Getting Bitbucket repo list')

        if url is None:
            url = (
                'https://api.bitbucket.org/2.0/repositories/%s' % self.project)

        r = requests.get(url, auth=(self.username, self.password))

        ret = {}
        ret['list'] = []
        ret['next'] = None
        ret['status'] = True

        if r.status_code == 200:
            data = r.json()

            if 'next' in data:
                ret['next'] = data['next']

            for values in data['values']:
                ret['list'].append(values['name'])
        else:
            ret['status'] = False

        return ret

    def get_repo_list_all(self):
        self.log.debug('Getting list of all Bitbucket repos')

        ret = {}
        ret['list'] = []
        ret['status'] = False

        repo_list = self.get_repo_list()

        if repo_list['status']:
            ret['list'] = repo_list['list']
            ret['status'] = repo_list['status']

            while repo_list['next'] is not None:
                repo_list = self.get_repo_list(repo_list['next'])
                ret['list'] += repo_list['list']

        return ret


class Stash:
    # Stash API:
    # https://developer.atlassian.com/static/rest/stash/latest/stash-rest.html

    username = ''
    password = ''
    url = ''
    log = None

    def __init__(self, username, password, url, logger):
        self.username = username
        self.password = password
        self.url = url
        self.log = logger

        self.log.debug('Creating Stash object instance')

    def get_project_list(self):
        self.log.debug('Getting Stash project list')

        ret = {}
        ret['keys'] = []
        ret['names'] = []
        ret['status'] = True

        project_list = requests.get(
            '%s/projects' % self.url,
            auth=(self.username, self.password))

        if project_list.status_code == 200:
            data = project_list.json()

            for project in data['values']:
                ret['keys'].append(project['key'])
                ret['names'].append(project['name'])
        else:
            ret['status'] = False

        return ret

    def create_project(self, name, key):
        self.log.debug('Creating Stash project')

        payload = {
            'key': key,
            'name': name,
            'description': 'Migrated from Bitbucket'
        }

        r = requests.post(
            '%s/projects' % self.url,
            data=json.dumps(payload),
            auth=(self.username, self.password),
            headers={'Content-type': 'application/json'})

        ret = True
        if r.status_code != 201:
            ret = False

        return ret

    def get_repo_list(self, prj_key):
        self.log.debug('Getting Stash repo list')

        r = requests.get(
            '%s/projects/%s/repos' % (self.url, prj_key),
            auth=(self.username, self.password))

        ret = {}
        ret['list'] = []
        ret['status'] = True

        if r.status_code == 200:
            data = r.json()

            for values in data['values']:
                ret['list'].append(values['name'])
        else:
            ret['status'] = False

        return ret

    def create_repo(self, prj_key, repo):
        self.log.debug('Creating Stash repo')

        payload = {
            'name': repo,
            'scmId': 'git',
            'forkable': True
        }

        r = requests.post(
            '%s/projects/%s/repos' % (self.url, prj_key),
            data=json.dumps(payload),
            auth=(self.username, self.password),
            headers={'Content-type': 'application/json'})

        ret = True
        if r.status_code != 201:
            ret = False

        return ret


class Bitbucket2Stash:
    args = None
    config = None
    log = None

    def __init__(self, args, config, logger):
        self.args = args
        self.config = config
        self.log = logger

        self.log.debug('Creating Bitbucket2Stash object instance')

    def check_bitbucket(self):
        # Create Bitbucket object
        bb = Bitbucket(
            self.config.get('bitbucket', 'api_username'),
            self.config.get('bitbucket', 'api_password'),
            self.args['<bitbucket_prj>'],
            self.log)

        # Get list of all Bitbucket repos
        repo_list = bb.get_repo_list_all()

        # Check if Bitbucket project exists
        if not repo_list['status']:
            self.log.error(
                'Project "%s" does not exist!' % self.args['<bitbucket_prj>'])
            sys.exit(1)

        # Check if Bitbucket repo exists
        if self.args['<bitbucket_repo>'] not in repo_list['list']:
            self.log.error(
                'Repo "%s" does not exist!' % self.args['<bitbucket_repo>'])
            sys.exit(1)

    def check_stash(self):
        # Create Stash object
        stash = Stash(
            self.config.get('stash', 'api_username'),
            self.config.get('stash', 'api_password'),
            self.config.get('stash', 'api_url'),
            self.log)

        # Get list of Stash projects
        project_list = stash.get_project_list()

        # Check if the connection was successful
        if not project_list['status']:
            self.log.error('Can not get list of Stash projects!')
            sys.exit(1)

        repo_list = {}
        repo_list['list'] = []

        # Check if the project already exists
        if self.args['<stash_prj_key>'] not in project_list['keys']:
            self.log.debug(
                'Stash project "%s" does not exist' %
                self.args['<stash_prj_key>'])
            prj_success = stash.create_project(
                self.args['<stash_prj_name>'],
                self.args['<stash_prj_key>'])

            if not prj_success:
                self.log.error(
                    'Stash project "%s" was not created!' %
                    self.args['<stash_prj_key>'])
                sys.exit(1)
        else:
            # Get list of repos from the Stash project
            repo_list = stash.get_repo_list(self.args['<stash_prj_key>'])

            # Check if the connection was successful
            if not repo_list['status']:
                self.log.error('Can not get list of Stash repos!')
                sys.exit(1)

        # Check if the Stash repo exists
        if self.args['<stash_repo>'] not in repo_list['list']:
            # Create Stash repo
            repo_success = stash.create_repo(
                self.args['<stash_prj_key>'],
                self.args['<stash_repo>'])

            if not repo_success:
                self.log.error(
                    'Stash repo "%s" was not created!' %
                    self.args['<stash_repo>'])
                sys.exit(1)

    def copy_repo(self):
        # Define the temporal repo directory
        tmp_repo_dir = os.path.join(
            tempfile.gettempdir(),
            self.args['<stash_repo>'])

        # Delete the local repo if exists
        if os.path.exists(tmp_repo_dir):
            self.log.debug('Deleting old local repo')
            shutil.rmtree(tmp_repo_dir)

        # Clone Bitbucket repo
        self.log.debug('Cloning Bitbucket repo')
        cloned_repo = git.Repo.clone_from(
            '%sbitbucket.org/%s/%s.git' % (
                self.config.get('bitbucket', 'git_protocol'),
                self.args['<bitbucket_prj>'],
                self.args['<bitbucket_repo>']
            ),
            tmp_repo_dir,
            bare=True
        )

        # Push repo to Stash
        self.log.debug('Pushing repo to Stash')
        tmp_repo = git.Repo(tmp_repo_dir)
        tmp_repo.delete_remote('origin')
        tmp_repo_origin = tmp_repo.create_remote(
            'origin', url='%s/%s/%s.git' % (
                self.config.get('stash', 'git_url'),
                self.args['<stash_prj_key>'].lower(),
                self.args['<stash_repo>']
            )
        )
        tmp_repo_origin.push(mirror=True)

        # Delete the local temporal repo
        self.log.debug('Deleting local temporal repo')
        shutil.rmtree(tmp_repo_dir)


def main():
    # Load command line options
    args = docopt(__doc__, version='0.1')

    if args['<stash_repo>'] is None:
        args['<stash_repo>'] = args['<bitbucket_repo>']

    # Set logging
    log = logging.getLogger(__name__)
    level = logging.INFO
    logging.getLogger("requests").setLevel(logging.WARNING)
    if args['--quiet']:
        level = logging.ERROR
    elif args['--debug']:
        level = logging.DEBUG
        logging.getLogger("requests").setLevel(logging.DEBUG)
    logging.basicConfig(
        format='[%(asctime)s] %(levelname)s: %(message)s', level=level)

    # Read config file
    log.debug('Reading config file')
    config = ConfigParser.RawConfigParser()
    config.read(args['--config'])

    if args['list'] and args['bitbucket'] and args['repos']:
        log.info(
            'List of repos for Bitbucket project %s' % args['<bitbucket_prj>'])

        # Create Bitbucket object
        bb = Bitbucket(
            config.get('bitbucket', 'api_username'),
            config.get('bitbucket', 'api_password'),
            args['<bitbucket_prj>'],
            log)

        # Get list of all Bitbucket repos
        repo_list = bb.get_repo_list_all()

        # Check if Bitbucket project exists
        if not repo_list['status']:
            log.error(
                'Project "%s" does not exist!' % args['<bitbucket_prj>'])
            sys.exit(1)

        # Print the result
        for repo in sorted(repo_list['list']):
            print repo
    elif args['list'] and args['stash']:
        # Create Stash object
        stash = Stash(
            config.get('stash', 'api_username'),
            config.get('stash', 'api_password'),
            config.get('stash', 'api_url'),
            log)

        if args['projects']:
            log.info('List of Stash projects')

            # Get list of Stash projects
            project_list = stash.get_project_list()

            # Check if the connection was successful
            if not project_list['status']:
                log.error('Can not get list of Stash projects!')
                sys.exit(1)

            # Print the result
            for prj in sorted(project_list['keys']):
                print prj
        elif args['repos']:
            log.info(
                'List of repos for Stash project %s' % args['<stash_prj_key>'])

            # Get list of repos from the Stash project
            repo_list = stash.get_repo_list(args['<stash_prj_key>'])

            # Check if the connection was successful
            if not repo_list['status']:
                log.error('Can not get list of Stash repos!')
                sys.exit(1)

            # Print the result
            for repo in sorted(repo_list['list']):
                print repo
    else:
        log.info('Processing Bitbucket{%s/%s} ~> Stash{%s(%s)/%s}' % (
            args['<bitbucket_prj>'],
            args['<bitbucket_repo>'],
            args['<stash_prj_name>'],
            args['<stash_prj_key>'],
            args['<stash_repo>']
        ))

        # Do the migration
        migrate = Bitbucket2Stash(args, config, log)
        migrate.check_bitbucket()
        migrate.check_stash()
        migrate.copy_repo()


if __name__ == '__main__':
    main()
