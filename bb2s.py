#!/usr/bin/env python2

'''
Script which helps to migrate Git repos from Bitbucket to Stash.

Usage:
  bb2s [options] list bitbucket [repos] <bitbucket_prj>
  bb2s [options] list stash (projects|repos <stash_prj_key>)
  bb2s [options] <bitbucket_prj> <bitbucket_repo> <stash_prj_name> \
<stash_prj_key> [<stash_repo>]
  bb2s -h | --help
  bb2s --version

Options:
  -c FILE --config=FILE  Config file path [default: bb2s.ini].
  -k --keys              Handle SSH keys.
  -q --quiet             Do not show any messages.
  -d --debug             Show debug messages.
  -h --help              Show this screen.
  --version              Show version.
'''

from docopt import docopt
import ConfigParser
import git
import json
import logging
import os
import re
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
    keys = False

    def __init__(self, username, password, project, logger, keys=False):
        self.username = username
        self.password = password
        self.project = project
        self.log = logger
        self.keys = keys

        self.log.debug('Creating Bitbucket object instance')

    def get_repo_list(self):
        self.log.debug('Getting Bitbucket repo list')

        url = 'https://api.bitbucket.org/2.0/repositories/%s' % self.project

        ret = {}
        ret['list'] = []
        ret['keys'] = []
        ret['next'] = None
        ret['status'] = True
        next_url = None

        while url is not None:
            r = requests.get(url, auth=(self.username, self.password))

            if r.status_code == 200:
                data = r.json()

                if 'next' in data:
                    url = data['next']
                else:
                    url = None

                for values in data['values']:
                    repo_name = values['full_name'].split('/')[1]
                    ret['list'].append(repo_name)

                    if self.keys:
                        keys = self.get_repo_keys(repo_name)

                        if keys['status'] == True:
                            ret['keys'].append(len(keys['list']))
            else:
                ret['status'] = False
                url = None

        return ret

    def get_repo_keys(self, repo):
        self.log.debug('Getting list of all Bitbucket repo keys')

        url = (
            'https://api.bitbucket.org/1.0/repositories/%s/%s/deploy-keys' %
            (self.project, repo))

        r = requests.get(url, auth=(self.username, self.password))

        ret = {}
        ret['list'] = []
        ret['status'] = True

        if r.status_code == 200:
            ret['list'] = r.json()
        else:
            ret['status'] = False

        return ret


class Stash:
    # Stash API:
    # https://developer.atlassian.com/static/rest/stash/latest/stash-rest.html
    # https://developer.atlassian.com/static/rest/stash/latest/stash-ssh-rest.html

    username = ''
    password = ''
    url = ''
    log = None
    limit = 100

    def __init__(self, username, password, url, logger):
        self.username = username
        self.password = password
        self.url = url
        self.log = logger

        self.log.debug('Creating Stash object instance')

    def get_project_list(self):
        self.log.debug('Getting Stash project list')

        ret = {}
        ret['names'] = []
        ret['keys'] = []
        ret['status'] = True
        last = False
        start = 0

        while not last:
            project_list = requests.get(
                '%s/api/latest/projects?limit=%d&start=%d' %
                (self.url, self.limit, start),
                auth=(self.username, self.password))

            if project_list.status_code == 200:
                data = project_list.json()
                last = data['isLastPage']

                if not last:
                    start = data['nextPageStart']

                for project in data['values']:
                    ret['names'].append(project['name'])
                    ret['keys'].append(project['key'].lower())
            else:
                ret['status'] = False
                last = True

        return ret

    def create_project(self, name, key):
        self.log.debug('Creating Stash project')

        payload = {
            'key': key.upper(),
            'name': name,
            'description': 'Migrated from Bitbucket'
        }

        r = requests.post(
            '%s/api/latest/projects' % self.url,
            data=json.dumps(payload),
            auth=(self.username, self.password),
            headers={'Content-type': 'application/json'})

        ret = True
        if r.status_code != 201:
            ret = False

        return ret

    def get_repo_list(self, prj_key):
        self.log.debug('Getting Stash repo list')

        ret = {}
        ret['list'] = []
        ret['status'] = True
        last = False
        start = 0

        while not last:
            r = requests.get(
                '%s/api/latest/projects/%s/repos?limit=%d&start=%d' %
                (self.url, prj_key, self.limit, start),
                auth=(self.username, self.password))

            if r.status_code == 200:
                data = r.json()
                last = data['isLastPage']

                if not last:
                    start = data['nextPageStart']

                for values in data['values']:
                    ret['list'].append(values['slug'])
            else:
                ret['status'] = False
                last = True

        return ret

    def create_repo(self, prj_key, repo):
        self.log.debug('Creating Stash repo')

        payload = {
            'name': repo,
            'scmId': 'git',
            'forkable': True
        }

        r = requests.post(
            '%s/api/latest/projects/%s/repos' % (self.url, prj_key),
            data=json.dumps(payload),
            auth=(self.username, self.password),
            headers={'Content-type': 'application/json'})

        ret = True
        if r.status_code != 201:
            ret = False

        return ret

    def get_repo_keys(self, prj_key, repo):
        self.log.debug('Getting list of all Stash repo keys')

        ret = {}
        ret['list'] = []
        ret['status'] = True
        last = False
        start = 0

        while not last:
            r = requests.get(
                '%s/keys/latest/projects/%s/repos/%s/ssh?limit=%d&start=%d' %
                (self.url, prj_key, repo, self.limit, start),
                auth=(self.username, self.password))

            if r.status_code == 200:
                data = r.json()
                last = data['isLastPage']

                if not last:
                    start = data['nextPageStart']

                for values in data['values']:
                    ret['list'].append(values['key'])
            else:
                ret['status'] = False
                last = True

        return ret

    def add_repo_key(self, prj_key, repo, key):
        self.log.debug('Adding Stash repo key')

        ret = {}
        ret['status'] = False

        payload = {
            'key': {
                'text': key
            },
            'permission': 'REPO_WRITE'
        }

        r = requests.post(
            '%s/keys/latest/projects/%s/repos/%s/ssh' %
            (self.url, prj_key, repo),
            data=json.dumps(payload),
            auth=(self.username, self.password),
            headers={'Content-type': 'application/json'})

        if r.status_code == 201:
            ret['status'] = True

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
        repo_list = bb.get_repo_list()

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
                self.args['<stash_prj_key>'],
                self.args['<stash_repo>']
            )
        )
        tmp_repo_origin.push(mirror=True)

        # Delete the local temporal repo
        self.log.debug('Deleting local temporal repo')
        shutil.rmtree(tmp_repo_dir)

    def copy_keys(self):
        # Create Bitbucket object
        bb = Bitbucket(
            self.config.get('bitbucket', 'api_username'),
            self.config.get('bitbucket', 'api_password'),
            self.args['<bitbucket_prj>'],
            self.log)

        # Get list of all Bitbucket repos
        bb_keys_list = bb.get_repo_keys(self.args['<bitbucket_repo>'])

        # Check if the connection was successful
        if not bb_keys_list['status']:
            self.log.error('Can not get list of Bitbucket repo keys!')
            sys.exit(1)

        # No keys to copy over
        if len(bb_keys_list['list']) == 0:
            return

        # Create Stash object
        stash = Stash(
            self.config.get('stash', 'api_username'),
            self.config.get('stash', 'api_password'),
            self.config.get('stash', 'api_url'),
            self.log)

        # Get list of Stash projects
        stash_keys_list = stash.get_repo_keys(
            self.args['<stash_prj_key>'],
            self.args['<stash_repo>'])

        # Check if the connection was successful
        if not stash_keys_list['status']:
            self.log.error('Can not get list of Stash repo keys!')
            sys.exit(1)

        key_found = False

        # Compare keys
        for bb_key in bb_keys_list['list']:
            bb_k = re.split('\s+', bb_key['key'])[1]

            for stash_key in stash_keys_list['list']:
                stash_k = re.split('\s+', stash_key['text'])[1]

                if bb_k == stash_k:
                    key_found = True
                    break

            if not key_found:
                # Add the key
                success = stash.add_repo_key(
                    self.args['<stash_prj_key>'],
                    self.args['<stash_repo>'],
                    bb_key['key'])

                if not success['status']:
                    self.log.error("Can not add Stash repo key")
                    sys.exit(1)

    def list_bitbucket_repos(self):
        self.log.info(
            'List of repos for Bitbucket project %s' %
            self.args['<bitbucket_prj>'])

        # Create Bitbucket object
        bb = Bitbucket(
            self.config.get('bitbucket', 'api_username'),
            self.config.get('bitbucket', 'api_password'),
            self.args['<bitbucket_prj>'],
            self.log,
            self.args['--keys'])

        # Get list of all Bitbucket repos
        repo_list = bb.get_repo_list()

        # Check if Bitbucket project exists
        if not repo_list['status']:
            self.log.error(
                'Project "%s" does not exist!' % self.args['<bitbucket_prj>'])
            sys.exit(1)

        # Print the result
        for repo, keys in sorted(zip(repo_list['list'], repo_list['keys'])):
            if self.args['--keys']:
                print '%s\t[keys: %d]' % (repo, keys)
            else:
                print repo

    def list_stash_projects(self):
        self.log.info('List of Stash projects')

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

        # Print the result
        if self.args['--keys']:
            for key in sorted(project_list['keys']):
                print key
        else:
            for name in sorted(project_list['names']):
                print name

    def list_stash_repos(self):
        self.log.info(
            'List of repos for Stash project %s' %
            self.args['<stash_prj_key>'])

        # Create Stash object
        stash = Stash(
            self.config.get('stash', 'api_username'),
            self.config.get('stash', 'api_password'),
            self.config.get('stash', 'api_url'),
            self.log)
        # Get list of repos from the Stash project
        repo_list = stash.get_repo_list(self.args['<stash_prj_key>'])

        # Check if the connection was successful
        if not repo_list['status']:
            self.log.error('Can not get list of Stash repos!')
            sys.exit(1)

        # Print the result
        for repo in sorted(repo_list['list']):
            print repo


def main():
    # Load command line options
    args = docopt(__doc__, version='0.1')

    # Default default Stash repo name
    if args['<stash_repo>'] is None:
        args['<stash_repo>'] = args['<bitbucket_repo>']

    # Make the Stash project key lowercase
    if args['<stash_prj_key>']:
        args['<stash_prj_key>'] = args['<stash_prj_key>'].lower()

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

    bb2s = Bitbucket2Stash(args, config, log)

    # Do action
    if args['list'] and args['bitbucket'] and args['repos']:
        bb2s.list_bitbucket_repos()
    elif args['list'] and args['stash'] and args['projects']:
        bb2s.list_stash_projects()
    elif args['list'] and args['stash'] and args['repos']:
        bb2s.list_stash_repos()
    else:
        log.info('Migrating Bitbucket{%s/%s} ~> Stash{%s(%s)/%s}' % (
            args['<bitbucket_prj>'],
            args['<bitbucket_repo>'],
            args['<stash_prj_name>'],
            args['<stash_prj_key>'],
            args['<stash_repo>']
        ))

        bb2s.check_bitbucket()
        bb2s.check_stash()
        bb2s.copy_repo()

        if args['--keys']:
            bb2s.copy_keys()


if __name__ == '__main__':
    main()
