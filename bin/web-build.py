#!/usr/bin/env python
"""
This builds a Github Pages site using the phantom (and possibly other) QC
plots generated by datman, commits those changes, and finally pushes them
up to github. This way, the online dashboards can be updated automatically.

Usage:
    web-build.py [options] <project>

Arguments: 
    <project>           Full path to the project directory containing data/.

Options:
    -v,--verbose             Verbose logging
    --debug                  Debug logging

DETAILS

    This finds outputs of qc-phantom.py (and potentially eventually qc.py),
    converts those files to a web-friendly format, and builds a gh-pages
    formatted post in the website/ folder.

    This assumes you've set up the website/ folder using the template. 

    Currently, this will outputs one post for ADNI and fMRI fBIRN phantom
    plots. It should also produce similar plots for the fBIRN DTI pipeline 
    soon.

DEPENDENCIES

    + imagemagick

    This message is printed with the -h, --help flags.
"""

import sys, os
from copy import copy
from docopt import docopt


VERBOSE = False
DRYRUN  = False
DEBUG   = False

# template text used to generate each post note Y2K+100 BUG!
HEADER = """\
---
category: {imagetype}
title: {imagetype} 20{date}
tags: [{imagetype}]
---
"""

BODY = """\
<figure>
    <a href="{{{{ production_url }}}}/{proj}/assets/images/{imagetype}/{fname}">\
<img src="{{{{ production_url }}}}/{proj}/assets/images/{imagetype}/{fname}"></a>
</figure>

"""


def filter_posted(files, dates):
    """
    This removes files containing any of the dates supplied in the filename.
    """
    for date in dates:
        files = filter(lambda x: date not in x, files)

    return files

def get_unique_dates(files, begin=2, end=10):
    """
    Gets all the unique dates in a list of input files. Defined as a region 
    of the input file that begins at 'begin' and ends and 'end.'
    """
    dates = copy(files)
    for i, f in enumerate(files):
        dates[i] = f[begin:end]
    dates = list(set(dates))

    return dates

def get_posted_dates(base_path):
    """
    This gets all of the currently posted dates from the website.
    """
    try:
        posts = os.listdir('{}/website/_posts/'.format(base_path))
        posts = get_unique_dates(posts, 2, 10)

    except:
        print("""Bro, you don't even have a website."""
              """Clone one into website/ from"""
              """https://github.com/TIGRLab/data-website""")
        sys.exit()

    return posts

def get_new_files(base_path, dates):
    """
    This gets the output pdfs for the adni, fmri, and dti qc plots, and 
    returns each as a list. If a type of these outputs does not exist for
    a given study, we return None for that type.

    We also filter out any of these that have already been posted.
    """
    try:
        adni = os.listdir('{}/qc/phantom/adni'.format(base_path))
        adni = filter(lambda x: '.pdf' in x, adni)
        adni = filter_posted(adni, dates)
        adni.sort()

        if len(adni) == 0:
            adni = None
    except:
        adni = None

    try:
        fmri = os.listdir('{}/qc/phantom/fmri'.format(base_path))
        fmri = filter(lambda x: '.pdf' in x, fmri)
        fmri = filter_posted(fmri, dates)
        fmri.sort()

        if len(fmri) == 0:
            fmri = None
    except:
        fmri = None

    try:
        dti = os.listdir('{}/qc/phantom/dti'.format(base_path))
        dti = filter(lambda x: '.pdf' in x, dti)
        dti = filter_posted(dti, dates)
        dti.sort()

        if len(dti) == 0:
            dti = None
    except:
        dti = None

    return adni, fmri, dti

def get_imagetype_from_filename(filename):
    """
    Determines the type of plot from the filename.
    """
    if 'adni' in filename.lower():
        imagetype = 'adni'
    elif 'fmri' in filename.lower():
        imagetype = 'fmri'
    elif 'dti' in filename.lower():
        imagetype = 'dti'
    else:
        print('ERROR: Unknown input file ' + f)
        imagetype = None

    return imagetype

def convert_to_web(base_path, files):
    """
    Converts .pdfs to .pngs in the website folder. Also changes the associated
    filenames to contain the new file extensions.
    """
    for i, f in enumerate(files):
        imagetype = get_imagetype_from_filename(f) 
        cmd = ('convert '
               '{base_path}/qc/phantom/{imagetype}/{f} '
               '{base_path}/website/assets/images/{imagetype}/{out_f}'.format(
                    base_path=base_path, imagetype=imagetype, 
                    f=f, out_f=f[:-4] + '.png'))
        os.system(cmd)
        files[i] = f[:-4] + '.png'

    return files

def create_posts(base_path, files):
    """
    Loops through unique dates, and generates a jekyll post for each one using
    all of the images from that date.
    """

    proj = dm.utils.mangle_basename(base_path)
    imagetype = get_imagetype_from_filename(files[0])
    dates = get_unique_dates(files, 0, 8)

    for date in dates:
        
        current_files = filter(lambda x: date in x, files)

        # NB: Y2K+100 BUG
        post_name = '{base_path}/website/_posts/{date}-{imagetype}.md'.format(
                        base_path=base_path, 
                        date='20' + date, 
                        imagetype=imagetype)
        
        # write header, loop through files, write body for each
        f = open(post_name, 'wb')
        f.write(HEADER.format(imagetype=imagetype, date=date))
        for fname in current_files:
             f.write(BODY.format(proj=proj, imagetype=imagetype, fname=fname))
        f.close()

        print('Wrote page for ' + imagetype + ' ' + date + '.')

def main():

    arguments = docopt(__doc__)
    project   = arguments['<project>']
    VERBOSE   = arguments['--verbose']
    DEBUG     = arguments['--debug']

    # finds all of the dates we've already posted
    dates = get_posted_dates(project)

    # gets a list of all the unposted pdfs
    adni, fmri, dti = get_new_files(project, dates)

    # converts uncopied pdfs to website, converts to .png, generates markdown
    if adni:
        print('converting ADNI')
        adni = convert_to_web(project, adni)
        create_posts(project, adni)

    if fmri:
        print('converting fMRI')
        fmri = convert_to_web(project, fmri)
        create_posts(project, fmri)

    if dti:
        dti = convert_to_web(project, dti)
        create_posts(project, dti)

if __name__ == '__main__':
    main()