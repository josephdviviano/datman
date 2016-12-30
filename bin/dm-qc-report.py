#!/usr/bin/env python
"""
Generates quality control reports on defined MRI data types. If no subject is
given, all subjects are submitted individually to the queue.

usage:
    dm-qc-report.py [options] <study>
    dm-qc-report.py [options] <study> <session>

Arguments:
    <study>           Name of the study to process e.g. ANDT
    <session>         Datman name of session to process e.g. DTI_CMH_H001_01_01

Options:
    --rewrite          Rewrite the html of an existing qc page
    --log-to-server    If set, all log messages will also be sent to the
                       configured logging server. This is useful when the script
                       is run with the Sun Grid Engine, since it swallows
                       logging messages.
    -q --quiet         Only report errors
    -v --verbose       Be chatty
    -d --debug         Be extra chatty

Details:
    This program QCs the data contained in <NiftiDir> and <DicomDir>, and
    outputs a myriad of metrics as well as a report in <QCDir>. All work is done
    on a per-subject basis.

    **data directories**

    The folder structure expected is that generated by xnat-export.py:

        <NiftiDir>/
           subject1/
               file1.nii.gz
               file2.nii.gz
           subject2/
               file1.nii.gz
               file2.nii.gz

        <DicomDir>/
           subject1/
               file1.dcm
               file2.dcm
           subject2/
               file1.dcm
               file2.dcm

     There should be a .dcm file for each .nii.gz. One subfolder for each
     subject will be created under the <QCDir> folder.

     **gold standards**

     To check for changes to the MRI machine's settings over time, this compares
     the headers found in <DicomDir> with the appropriate dicom file found in
     <StandardsDir>/<Tag>/filename.dcm.

     **configuration file**

     The locations of the dicom folder, nifti folder, qc folder, gold standards
     folder, log folder, and expected set of scans are read from the supplied
     configuration file with the following structure:

     paths:
       dcm: '/archive/data/SPINS/data/dcm'
       nii: '/archive/data/SPINS/data/nii'
       qc:  '/archive/data/SPINS/qc'
       std: '/archive/data/SPINS/metadata/standards'
       log: '/archive/data/SPINS/log'

     Sites:
       site1:
         XNAT_Archive: '/path/to/arc001'
         ExportInfo:
           - T1:  {Pattern: {'regex1', 'regex2'}, Count: n_expected}
           - DTI: {Pattern: {'regex1', 'regex2'}, Count: n_expected}
       site2 :
         XNAT_Archive: '/path/to/arc001'
         ExportInfo:
           - T1:  {Pattern: {'regex1', 'regex2'}, Count: n_expected}
           - DTI: {Pattern: {'regex1', 'regex2'}, Count: n_expected}
Requires:
    FSL
    QCMON
"""

import os, sys
import re
import glob
import time
import logging
import logging.handlers
import copy
import random
import string

import numpy as np
import pandas as pd
import nibabel as nib

import datman.config
import datman.utils
import datman.scanid
import datman.scan

from datman.docopt import docopt

logging.basicConfig(level=logging.WARN,
        format="[%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(os.path.basename(__file__))

REWRITE = False

def random_str(n):
    """generates a random string of length n"""
    return(''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n)))

def slicer(fpath, pic, slicergap, picwidth):
    """
    Uses FSL's slicer function to generate a montage png from a nifti file
        fpath       -- submitted image file name
        slicergap   -- int of "gap" between slices in Montage
        picwidth    -- width (in pixels) of output image
        pic         -- fullpath to for output image
    """
    datman.utils.run("slicer {} -S {} {} {}".format(fpath,slicergap,picwidth,pic))

def add_image(qc_html, image, title=None):
    """
    Adds an image to the report.
    """
    if title:
        qc_html.write('<center> {} </center>'.format(title))

    relpath = os.path.relpath(image, os.path.dirname(qc_html.name))
    qc_html.write('<a href="'+ relpath + '" >')
    qc_html.write('<img src="' + relpath + '" >')
    qc_html.write('</a><br>\n')

    return qc_html

# PIPELINES
def ignore(filename, qc_dir, report):
    pass

def phantom_fmri_qc(filename, outputDir):
    """
    Runs the fbirn fMRI pipeline on input phantom data if the outputs don't
    already exist.
    """
    basename = datman.utils.nifti_basename(filename)
    output_file = os.path.join(outputDir, '{}_stats.csv'.format(basename))
    output_prefix = os.path.join(outputDir, basename)
    if not os.path.isfile(output_file):
        datman.utils.run('qc-fbirn-fmri {} {}'.format(filename, output_prefix))

def phantom_dti_qc(filename, outputDir):
    """
    Runs the fbirn DTI pipeline on input phantom data if the outputs don't
    already exist.
    """
    dirname = os.path.dirname(filename)
    basename = datman.utils.nifti_basename(filename)

    output_file = os.path.join(outputDir, '{}_stats.csv'.format(basename))
    output_prefix = os.path.join(outputDir, basename)

    if not os.path.isfile(output_file):
        bvec = os.path.join(dirname, basename + '.bvec')
        bval = os.path.join(dirname, basename + '.bval')
        datman.utils.run('qc-fbirn-dti {} {} {} {} n'.format(filename, bvec, bval,
                output_prefix))

def phantom_anat_qc(filename, outputDir):
    """
    Runs the ADNI pipeline on input phantom data if the outputs don't already
    exist.
    """
    basename = datman.utils.nifti_basename(filename)
    output_file = os.path.join(outputDir, '{}_adni-contrasts.csv'.format(basename))
    if not os.path.isfile(output_file):
        datman.utils.run('qc-adni {} {}'.format(filename, output_file))

def fmri_qc(file_name, qc_dir, report):
    base_name = datman.utils.nifti_basename(file_name)
    output_name = os.path.join(qc_dir, base_name)

    # check scan length
    script_output = output_name + '_scanlengths.csv'
    if not os.path.isfile(script_output):
        datman.utils.run('qc-scanlength {} {}'.format(file_name, script_output))

    # check fmri signal
    script_output = output_name + '_stats.csv'
    if not os.path.isfile(script_output):
        datman.utils.run('qc-fmri {} {}'.format(file_name, output_name))

    image_raw = output_name + '_raw.png'
    image_sfnr = output_name + '_sfnr.png'
    image_corr = output_name + '_corr.png'

    if not os.path.isfile(image_raw):
        slicer(file_name, image_raw, 2, 1600)
    add_image(report, image_raw, title='BOLD montage')

    if not os.path.isfile(image_sfnr):
        slicer(os.path.join(qc_dir, base_name + '_sfnr.nii.gz'), image_sfnr, 2,
                1600)
    add_image(report, image_sfnr, title='SFNR map')

    if not os.path.isfile(image_corr):
        slicer(os.path.join(qc_dir, base_name + '_corr.nii.gz'), image_corr, 2,
                1600)
    add_image(report, image_corr, title='correlation map')

def anat_qc(filename, qc_dir, report):

    image = os.path.join(qc_dir, datman.utils.nifti_basename(filename) + '.png')
    if not os.path.isfile(image):
        slicer(filename, image, 5, 1600)
    add_image(report, image)

def dti_qc(filename, qc_dir, report):
    dirname = os.path.dirname(filename)
    basename = datman.utils.nifti_basename(filename)

    bvec = os.path.join(dirname, basename + '.bvec')
    bval = os.path.join(dirname, basename + '.bval')

    output_prefix = os.path.join(qc_dir, basename)
    output_file = output_prefix + '_stats.csv'
    if not os.path.isfile(output_file):
       datman.utils.run('qc-dti {} {} {} {}'.format(filename, bvec, bval,
                output_prefix))

    output_file = os.path.join(qc_dir, basename + '_spikecount.csv')
    if not os.path.isfile(output_file):
        datman.utils.run('qc-spikecount {} {} {}'.format(filename,
                os.path.join(qc_dir, basename + '_spikecount.csv'), bval))

    image = os.path.join(qc_dir, basename + '_b0.png')
    if not os.path.isfile(image):
        slicer(filename, image, 2, 1600)
    add_image(report, image, title='b0 montage')
    add_image(report, os.path.join(qc_dir, basename + '_directions.png'),
            title='bvec directions')

def submit_qc_jobs(commands, chained=False):
    """
    Submits the given commands to the queue. In chained mode, each job will wait
    for the previous job to finish before attempting to run.
    """
    for i, cmd in enumerate(commands):
        if chained and i > 0:
            lastjob = copy.copy(jobname)
        jobname = "qc_report_{}_{}_{}".format(time.strftime("%Y%m%d"), random_str(5), i)
        logfile = '/tmp/{}.log'.format(jobname)
        errfile = '/tmp/{}.err'.format(jobname)

        if chained and i > 0:
            run_cmd = 'echo {} | qsub -V -q main.q -hold_jid {} -o {} -e {} -N {}'.format(cmd, lastjob, logfile, errfile, jobname)
        else:
            run_cmd = 'echo {} | qsub -V -q main.q -o {} -e {} -N {}'.format(cmd, logfile, errfile, jobname)

        rtn, out = datman.utils.run(run_cmd)

        if rtn:
            logger.error("stdout: {}".format(out))
        elif out:
            logger.debug(out)

def make_qc_command(subject_id, study):
    arguments = docopt(__doc__)
    use_server = arguments['--log-to-server']
    verbose = arguments['--verbose']
    debug = arguments['--debug']
    quiet = arguments['--quiet']
    command = " ".join([__file__, study, subject_id])
    if verbose:
        command = " ".join([command, '-v'])
    if debug:
        command = " ".join([command, '-d'])
    if quiet:
        command = " ".join([command, '-q'])
    if use_server:
        command = " ".join([command, '--log-to-server'])

    if REWRITE:
        command = command + ' --rewrite'

    return command

def qc_all_scans(config):
    """
    Creates a dm-qc-report.py command for each scan and submits all jobs to the
    queue. Phantom jobs are submitted in chained mode, which means they will run
    one at a time. This is currently needed because some of the phantom pipelines
    use expensive and limited software liscenses (i.e., MATLAB).
    """
    human_commands = []
    phantom_commands = []

    nii_dir = config.get_path('nii')

    for path in os.listdir(nii_dir):
        subject = os.path.basename(path)
        command = make_qc_command(subject, config.study_name)

        if '_PHA_' in subject:
            phantom_commands.append(command)
        else:
            human_commands.append(command)

    if human_commands:
        logger.debug('submitting human qc jobs\n{}'.format(human_commands))
        submit_qc_jobs(human_commands)

    if phantom_commands:
        logger.debug('running phantom qc jobs\n{}'.format(phantom_commands))
        submit_qc_jobs(phantom_commands, chained=True)

def find_existing_reports(checklist_path):
    found_reports = []
    with open(checklist_path, 'r') as checklist:
        for checklist_entry in checklist:
            checklist_entry = checklist_entry.split(' ')[0].strip()
            checklist_entry, checklist_ext = os.path.splitext(checklist_entry)
            found_reports.append(checklist_entry)
    return found_reports

def add_report_to_checklist(qc_report, checklist_path, retry=3):
    """
    Add the given report's name to the QC checklist if it is not already
    present.
    """
    if not qc_report or retry == 0:
        return

    # remove extension from report name, so we don't double-count .pdfs vs .html
    report_file_name = os.path.basename(qc_report)
    report_name, report_ext = os.path.splitext(report_file_name)

    try:
        found_reports = find_existing_reports(checklist_path)
    except IOError:
        logger.info("{} does not exist. "\
                "Attempting to create it".format(checklist_path))
        found_reports = []

    if report_name in found_reports:
        return

    try:
        with open(checklist_path, 'a') as checklist:
            checklist.write(report_file_name + '\n')
    except:
        logger.debug("Failed to write {} to checklist. Tries remaining: "
                "{}".format(report_file_name, retry))
        add_report_to_checklist(qc_report, checklist_path, retry=retry-1)

def add_header_qc(nifti, qc_html, log_path):
    """
    Adds header-diff.log information to the report.
    """
    # get the filename of the nifti in question
    filestem = nifti.file_name.replace(nifti.ext, '')

    try:
        # read the log
        with open(log_path, 'r') as f:
            f = f.readlines()
    except IOError:
        logger.info("header-diff.log not found. Generating page without it.")
        f = []

    # find lines in said log that pertain to the nifti
    lines = [re.sub('^.*?: *','',line) for line in f if filestem in line]

    if not lines:
        return

    qc_html.write('<h3> {} header differences </h3>\n<table>'.format(filestem))
    for l in lines:
        qc_html.write('<tr><td>{}</td></tr>'.format(l))
    qc_html.write('</table>\n')

def write_report_body(report, expected_files, subject, header_diffs, handlers):
    for idx in range(0,len(expected_files)):
        series = expected_files.loc[idx,'File']
        if not series:
            continue

        logger.info("QC scan {}".format(series.path))
        report.write('<h2 id="{}">{}</h2>\n'.format(expected_files.loc[idx,'bookmark'],
                series.file_name))

        if series.tag not in handlers:
            logger.info("No QC tag {} for scan {}. Skipping.".format(series.tag,
                    series.path))
            continue

        add_header_qc(series, report, header_diffs)

        try:
            handlers[series.tag](series.path, subject.qc_path, report)
        except KeyError:
            raise KeyError('series tag {} not defined in handlers:\n{}'.format(series.tag, handlers))
        report.write('<br>')

def find_tech_notes(path):
    """
    Search the file tree rooted at path for the tech notes pdf.

    If only one pdf is found it is assumed to be the tech notes. If multiple
    are found, unless one contains the string 'TechNotes', the first pdf is
    guessed to be the tech notes.
    """
    resource_folders = glob.glob(path + "*")

    if resource_folders:
        resources = resource_folders[0]
    else:
        resources = ""

    pdf_list = []
    for root, dirs, files in os.walk(resources):
        for fname in files:
            if ".pdf" in fname:
                pdf_list.append(os.path.join(root, fname))

    if not pdf_list:
        return ""
    elif len(pdf_list) > 1:
        for pdf in pdf_list:
            file_name = os.path.basename(pdf)
            if 'technotes' in file_name.lower():
                return pdf

    return pdf_list[0]

def write_tech_notes_link(report, subject_id, resources_path):
    """
    Adds a link to the tech notes for this subject to the given QC report
    """
    if 'CMH' not in subject_id:
        return

    tech_notes = find_tech_notes(resources_path)

    if not tech_notes:
        report.write('<p>Tech Notes not found</p>\n')
        return

    notes_path = os.path.relpath(os.path.abspath(tech_notes),
                        os.path.dirname(report.name))
    report.write('<a href="{}">'.format(notes_path))
    report.write('Click Here to open Tech Notes')
    report.write('</a><br>')

def write_table(report, exportinfo, subject):
    report.write('<table><tr>'
                 '<th>Tag</th>'
                 '<th>File</th>'
                 '<th>Scanlength</th>'
                 '<th>Notes</th></tr>')

    for row in range(0,len(exportinfo)):
        #Fetch Scanlength from .nii File
        scan_nii_path = os.path.join(subject.nii_path, str(exportinfo.loc[row, 'File']))
        try:
            data = nib.load(scan_nii_path)
            try:
                scanlength = data.shape[3]
            except:
                #Note: this might be expected, e.g., for a T1
                logging.debug("{} exists but scanlength cannot be read.".format(scan_nii_path))
                scanlength = "N/A"
        except:
            logging.debug("{} does not exist; cannot read scanlength.".format(scan_nii_path))
            scanlength = "No file"
        report.write('<tr><td>{}</td>'.format(exportinfo.loc[row,'tag'])) ## table new row
        report.write('<td><a href="#{}">{}</a></td>'.format(exportinfo.loc[row,
                'bookmark'], exportinfo.loc[row,'File']))
        report.write('<td>{}</td>'.format(scanlength))
        report.write('<td><font color="#FF0000">{}</font></td>'\
                '</tr>'.format(exportinfo.loc[row,'Note'])) ## table new row
    report.write('</table>\n')

def write_report_header(report, subject_id):
    report.write('<HTML><TITLE>{} qc</TITLE>\n'.format(subject_id))
    report.write('<head>\n<style>\n'
                'body { font-family: futura,sans-serif;'
                '        text-align: center;}\n'
                'img {width:90%; \n'
                '   display: block\n;'
                '   margin-left: auto;\n'
                '   margin-right: auto }\n'
                'table { margin: 25px auto; \n'
                '        border-collapse: collapse;\n'
                '        text-align: left;\n'
                '        width: 90%; \n'
                '        border: 1px solid grey;\n'
                '        border-bottom: 2px solid black;} \n'
                'th {background: black;\n'
                '    color: white;\n'
                '    text-transform: uppercase;\n'
                '    padding: 10px;}\n'
                'td {border-top: thin solid;\n'
                '    border-bottom: thin solid;\n'
                '    padding: 10px;}\n'
                '</style></head>\n')

    report.write('<h1> QC report for {} <h1/>'.format(subject_id))

def generate_qc_report(report_name, subject, expected_files, header_diffs, handlers):
    try:
        with open(report_name, 'wb') as report:
            write_report_header(report, subject.full_id)
            write_table(report, expected_files, subject)
            write_tech_notes_link(report, subject.full_id, subject.resource_path)
            write_report_body(report, expected_files, subject, header_diffs, handlers)
    except:
        raise

def get_position(position_info):
    if isinstance(position_info, list):
        position = position_info.pop(0)
    else:
        position = position_info

    return position

def initialize_counts(export_info):
    # build a tag count dict
    tag_counts = {}
    expected_position = {}

    for tag in export_info.tags:
        tag_counts[tag] = 0
        tag_info = export_info.get_tag_info(tag)

        # If ordering has been imposed on the scans get it for later sorting.
        if 'Order' in tag_info.keys():
            expected_position[tag] = min([tag_info['Order']])
        else:
            expected_position[tag] = 0

    return tag_counts, expected_position

def find_expected_files(subject, config):
    """
    Reads the export_info from the config for this site and compares it to the
    contents of the nii folder. Data written to a pandas dataframe.
    """
    export_info = config.get_export_info_object(subject.site)
    sorted_niftis = sorted(subject.niftis, key=lambda item: item.series_num)

    tag_counts, expected_positions = initialize_counts(export_info)

    # init output pandas data frame, counter
    idx = 0
    expected_files = pd.DataFrame(columns=['tag', 'File', 'bookmark', 'Note',
            'Sequence'])

    # tabulate found data in the order they were acquired
    for nifti in sorted_niftis:
        tag = nifti.tag

        # only check data that is defined in the config file
        if tag in export_info.tags:
            tag_info = export_info.get_tag_info(tag)
            expected_count = tag_info['Count']
        else:
            continue

        tag_counts[tag] += 1
        bookmark = tag + str(tag_counts[tag])
        if tag_counts[tag] > expected_count:
            notes = 'Repeated Scan'
        else:
            notes = ''

        position = get_position(expected_positions[tag])

        expected_files.loc[idx] = [tag, nifti, bookmark, notes,
                position]
        idx += 1

    # note any missing data
    for tag in export_info.tags:
        expected_count = export_info.get_tag_info(tag)['Count']
        if tag_counts[tag] < expected_count:
            n_missing = expected_count - tag_counts[tag]
            notes = 'missing({})'.format(n_missing)
            expected_files.loc[idx] = [tag, '', '', notes,
                    expected_positions[tag]]
            idx += 1
    expected_files = expected_files.sort('Sequence')
    return(expected_files)

def get_standards(standard_dir, site):
    """
    Constructs a dictionary of standards for each standards file in
    standard_dir.

    If a standards file name raises ParseException it will be logged and
    omitted from the standards dictionary.
    """
    glob_path = os.path.join(standard_dir, "*")

    standards = {}
    misnamed_files = []
    for item in glob.glob(glob_path):
        try:
            standard = datman.scan.Series(item)
        except datman.scanid.ParseException:
            misnamed_files.append(item)
            continue
        if standard.site == site:
            standards[standard.tag] = standard

    if misnamed_files:
        logging.error("Standards files misnamed, ignoring: \n" \
                "{}".format("\n".join(misnamed_files)))

    return standards

def run_header_qc(subject, standard_dir, log_file):
    """
    For each .dcm file found in 'dicoms', find the matching site / tag file in
    'standards', and run qc-headers (from qcmon) on these files. Any
    are written to log_file.
    """

    if not subject.dicoms:
        logger.debug("No dicoms found in {}".format(subject.dcm_path))
        return

    standards_dict = get_standards(standard_dir, subject.site)

    for dicom in subject.dicoms:
        try:
            standard = standards_dict[dicom.tag]
        except KeyError:
            logger.debug('No standard with tag {} found in {}'.format(dicom.tag,
                    standard_dir))
            continue
        else:
            # run header check for dicom
            datman.utils.run('qc-headers {} {} {}'.format(dicom.path, standard.path,
                    log_file))

    if not os.path.exists(log_file):
        logger.error("header-diff.log not generated for {}. Check that gold " \
                "standards are present for this site.".format(subject.full_id))

def qc_subject(subject, config):
    """
    subject :           The created Scan object for the subject_id this run
    config :            The settings obtained from project_settings.yml

    Returns the path to the qc_<subject_id>.html file
    """
    handlers = {   # map from tag to QC function
        "T1"            : anat_qc,
        "T2"            : anat_qc,
        "PD"            : anat_qc,
        "PDT2"          : anat_qc,
        "FLAIR"         : anat_qc,
        "FMAP"          : ignore,
        "FMAP-6.5"      : ignore,
        "FMAP-8.5"      : ignore,
        "RST"           : fmri_qc,
        "EPI"           : fmri_qc,
        "SPRL"          : fmri_qc,
        "OBS"           : fmri_qc,
        "IMI"           : fmri_qc,
        "NBK"           : fmri_qc,
        "EMP"           : fmri_qc,
        "VN-SPRL"       : fmri_qc,
        "SID"           : fmri_qc,
        "MID"           : fmri_qc,
        "TRG"           : fmri_qc,
        "DTI"           : dti_qc,
        "DTI21"         : dti_qc,
        "DTI22"         : dti_qc,
        "DTI23"         : dti_qc,
        "DTI60-29-1000" : dti_qc,
        "DTI60-20-1000" : dti_qc,
        "DTI60-1000-20" : dti_qc,
        "DTI60-1000-29" : dti_qc,
        "DTI60-1000"    : dti_qc,
        "DTI60-b1000"   : dti_qc,
        "DTI33-1000"    : dti_qc,
        "DTI33-b1000"   : dti_qc,
        "DTI33-3000"    : dti_qc,
        "DTI33-b3000"   : dti_qc,
        "DTI33-4500"    : dti_qc,
        "DTI33-b4500"   : dti_qc,
        "DTI23-1000"    : dti_qc,
        "DTI69-1000"    : dti_qc,
    }

    report_name = os.path.join(subject.qc_path, 'qc_{}.html'.format(subject.full_id))

    if os.path.isfile(report_name):
        if not REWRITE:
            logger.debug("{} exists, skipping.".format(report_name))
            return
        os.remove(report_name)

    # header diff
    header_diffs = os.path.join(subject.qc_path, 'header-diff.log')
    if not os.path.isfile(header_diffs):
        run_header_qc(subject, config.get_path('std'), header_diffs)

    expected_files = find_expected_files(subject, config)

    try:
        # Update checklist even if report generation fails
        checklist_path = os.path.join(config.get_path('meta'), 'checklist.csv')
        add_report_to_checklist(report_name, checklist_path)
    except:
        logger.error("Error adding {} to checklist.".format(subject.full_id))

    try:
        generate_qc_report(report_name, subject, expected_files, header_diffs,
                handlers)
    except:
        logger.error("Exception raised during qc-report generation for {}. " \
                "Removing .html page.".format(subject.full_id), exc_info=True)
        if os.path.exists(report_name):
            os.remove(report_name)

    return report_name

def qc_phantom(subject, config):
    """
    subject:            The Scan object for the subject_id of this run
    config :            The settings obtained from project_settings.yml
    """
    handlers = {
        "T1"            : phantom_anat_qc,
        "RST"           : phantom_fmri_qc,
        "DTI60-1000"    : phantom_dti_qc,
    }

    logger.debug('qc {}'.format(subject))
    for nifti in subject.niftis:
        if nifti.tag not in handlers:
            logger.info("No QC tag {} for scan {}. Skipping.".format(nifti.tag, nifti.path))
            continue
        logger.debug('qc {}'.format(nifti.path))
        handlers[nifti.tag](nifti.path, subject.qc_path)

def qc_single_scan(subject, config):
    """
    Perform QC for a single subject or phantom. Return the report name if one
    was created.
    """

    if subject.is_phantom:
        logger.info("QC phantom {}".format(subject.nii_path))
        qc_phantom(subject, config)
        return

    logger.info("QC {}".format(subject.nii_path))
    qc_subject(subject, config)
    return

def verify_input_paths(path_list):
    """
    Ensures that each path in path_list exists. If a path (or paths) do not
    exist this is logged and sys.exit is raised.
    """
    broken_paths = []
    for path in path_list:
        if not os.path.exists(path):
            broken_paths.append(path)

    if broken_paths:
        logging.error("The following path(s) required for input " \
                "do not exist: \n" \
                "{}".format("\n".join(broken_paths)))
        sys.exit(1)

def prepare_scan(subject_id, config):
    """
    Makes a new Scan object for this participant, clears out any empty files
    from needed directories and ensures that if needed input directories do
    not exist that the program exits.
    """
    try:
        subject = datman.scan.Scan(subject_id, config)
    except datman.scanid.ParseException as e:
        logger.error(e, exc_info=True)
        sys.exit(1)

    verify_input_paths([subject.nii_path, subject.dcm_path])

    qc_dir = datman.utils.define_folder(subject.qc_path)
    # If qc_dir already existed and had empty files left over clean up
    datman.utils.remove_empty_files(qc_dir)

    return subject

def get_config(study):
    """
    Retrieves the configuration information for this site and checks
    that the expected paths are all defined.

    Will raise KeyError if an expected path has not been defined for this study.
    """
    logger.info('Loading config')

    try:
        config = datman.config.config(study=study)
    except KeyError:
        logger.error("Cannot find configuration info for study {}".format(study))
        sys.exit(1)

    required_paths = ['dcm', 'nii', 'qc', 'std', 'meta']

    for path in required_paths:
        try:
            config.get_path(path)
        except KeyError:
            logger.error('Path {} not found for project: {}'
                         .format(path, study))
            sys.exit(1)

    return config

def add_server_handler(config):
    server_ip = config.get_key('LOGSERVER')
    server_handler = logging.handlers.SocketHandler(server_ip,
            logging.handlers.DEFAULT_TCP_LOGGING_PORT)
    logger.addHandler(server_handler)

def set_logger_name(session):
    global logger
    if not session:
        # Use default log format
        return
    # Change to a logger with a name that includes the session being processed
    # so log entries of different processes can be distinguished from each other.
    logger = logging.getLogger("{} - {}".format(os.path.basename(__file__),
            session))

def main():
    global REWRITE

    arguments = docopt(__doc__)
    use_server = arguments['--log-to-server']
    verbose = arguments['--verbose']
    debug = arguments['--debug']
    quiet = arguments['--quiet']
    study = arguments['<study>']
    session = arguments['<session>']
    REWRITE = arguments['--rewrite']

    config = get_config(study)

    if use_server:
        set_logger_name(session)
        add_server_handler(config)

    if quiet:
        logger.setLevel(logging.ERROR)
    if verbose:
        logger.setLevel(logging.INFO)
    if debug:
        logger.setLevel(logging.DEBUG)

    if session:
        subject = prepare_scan(session, config)
        qc_single_scan(subject, config)
        return

    qc_all_scans(config)

if __name__ == "__main__":
    main()
