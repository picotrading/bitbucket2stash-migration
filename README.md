Bitbucket to Stash migration script
===================================

Description
-----------

This script helps to migrate Git repos from Bitbucket to Stash. It only migrates
bare Git repos and repo SSH keys (no pull requests, no issues, no access
management, ...). It creates Stash projects and repos if they do not exist. It is
safe to run the script multiple times even on partially migrated projects.


Usage
-----

```
$ ./bb2s.py --help
Script which helps to migrate Git repos from Bitbucket to Stash.

Usage:
  bb2s [options] list bitbucket repos <bitbucket_prj>
  bb2s [options] list stash (projects|repos <stash_prj_key>)
  bb2s [options] <bitbucket_prj> <bitbucket_repo> <stash_prj_name> <stash_prj_key> [<stash_repo>]
  bb2s -h | --help
  bb2s --version

Options:
  -c FILE --config=FILE  Config file path [default: bb2s.ini].
  -d --debug             Show debug messages.
  -q --quiet             Do not show any messages.
  -h --help              Show this screen.
  --version              Show version.
```

Example of how to migrate one Bitbucket project to the same project in Stash:

```
for REPO in $(./bb2s.py list bitbucket repos myproject); do
  ./bb2s.py -k myproject $REPO "My project" myproject;
done
```


Configuration
-------------

This script requires correct configuration of Bitbucket and Stash details in the
`bb2s.ini` file:

```
[bitbucket]
api_username=mybitbucketuser
api_password=myBitbucketP4ssw0rd
git_protocol=https://

[stash]
api_username=mystashuser
api_password=myStashP4ssw0rd
api_url=http://example.com:7990/stash/rest
git_url=https://example.com/stash/scm
```

It's possible to change the Git protocol from `https` to `ssh` for both the
Bitbucket and Stash. Just set `git_protocol=ssh://mybitbucketuser@` in the
`[bitbucket]` section and `git_url=ssh://mystashuser@example.com/stash/scm` in
the `[stash]` section.


Dependencies
------------

- [Python 2](https://www.python.org)
- [PythonGit](http://gitpython.readthedocs.org/en/stable)
- [docopt](http://docopt.org)


License
-------

MIT


Author
------

Jiri Tyr
