IceProd
=======

IceProd is a Python framework for distributed management of batch jobs.
It runs as a layer on top of other batch middleware, such as HTCondor,
and can pool together resources from different batch systems.
The primary purpose is to coordinate and administer many large sets of
jobs at once, keeping a history of the entire job lifecycle.

**Note:**

For IceCube users with CVMFS access, IceProd is already installed.
To load the environment execute::

    /cvmfs/icecube.wisc.edu/iceprod/latest/env-shell.sh

or::

    eval `/cvmfs/icecube.wisc.edu/iceprod/latest/setup.sh`

depending on whether you want to get a new shell or load the variables
into the current shell.

Installation
------------

**Platforms**:

IceProd should run on any Unix-like platform, although only
Linux has been extensively tested and can be recommented for production
deployment (even though Mac OS X is derived from BSD and supports kqueue, its
networking performance is generally poor so it is recommended only for
development use).

**Prerequisites**:

IceProd runs on python 2.7 and 3.3+

There are two types of database interface available:

* sqlite:  depends on apsw: https://github.com/rogerbinns/apsw
* mysql:   depends on mysqldb: https://pypi.python.org/pypi/MySQL-python

Other non-essential dependencies:

* nginx       (for ssl offloading and better security)
* squid       (for http proxy)
* libtool     (a globus dependency)
* perl 5.10   (a globus dependency)

  * perl modules: Archive::Tar Compress::Zlib Digest::MD5 File::Spec IO::Zlib Pod::Parser XML::Parser

* globus      (for gridftp)


**Installation**:

From the latest release:

Get the tarball link from https://github.com/WIPACrepo/iceprod/releases/latest

Then install like::

    pip install https://github.com/WIPACrepo/iceprod/archive/v2.0.0.tar.gz

**Installing from master**:

If you must install the dev version from master, do::

    pip install --upgrade git+git://github.com/WIPACrepo/iceprod.git#egg=iceprod

