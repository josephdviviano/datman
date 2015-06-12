#!/usr/bin/env python
"""
dm-proc-ea.py <experiment-directory> <scratch-directory> <script> <assets>

experiment-directory -- top level of the DATMAN project
scratch-directory -- a place to store temporary files
script -- a epitome pre-processing script that analyzes the fMRI data.
assets -- a folder containing: EA-timing.csv, EA-vid-lengths.csv

This auto-grad student fully analyzes the empathic accuracy task behavioural data.

1) Preprocesses MRI data.
2) Parses the supplied e-prime file and returns an AFNI-compatible GLM file. 
3) Runs the GLM analysis at the single-subject level.
"""

import os, sys
import copy
import numpy as np
import scipy.interpolate as interpolate
import nibabel as nib
import StringIO as io
import matplotlib.pyplot as plt
import datman.spins as spn

def log_parser(log):
    """
    This takes the EA task log file generated by e-prime and converts it into a
    set of numpy-friendly arrays (with mixed numeric and text fields.)

    pic -- 'Picture' lines, which contain the participant's ratings.
    res -- 'Response' lines, which contain their responses (unclear)
    vid -- 'Video' lines, which demark the start and end of trials.
    """
    # substitute for GREP -- finds 'eventtype' field.
    # required as this file has a different number of fields per line
    logname = copy.copy(log)
    log = open(log, "r").readlines()
    pic = filter(lambda s: 'Picture' in s, log)
    res = filter(lambda s: 'Response' in s, log)
    vid = filter(lambda s: 'Video' in s, log)

    # write out files from stringio blobs into numpy genfromtxt
    pic = np.genfromtxt(io.StringIO(''.join(pic)), delimiter='\t', 
                             dtype=[('subject', '|S64'), 
                                    ('trial', 'i32'),
                                    ('eventtype', '|S64'),
                                    ('code', '|S64'),
                                    ('time', 'i32'),
                                    ('ttime', 'i32'),
                                    ('uncertainty1', 'i32'),
                                    ('duration', 'i32'),
                                    ('uncertainty2', 'i32'),
                                    ('reqtime', 'i32'),
                                    ('reqduration', 'i32'),
                                    ('stimtype', '|S64'),
                                    ('pairindex', 'i32')])

    # code 104 == 'mri trigger'
    # 
    # 
    res = np.genfromtxt(io.StringIO(''.join(res)), delimiter='\t',
                             dtype=[('subject', '|S64'), 
                                    ('trial', 'i32'),
                                    ('eventtype', '|S64'),
                                    ('code', '|S64'),
                                    ('time', 'i32'),
                                    ('ttime', 'i32'),
                                    ('uncertainty1', 'i32')])

    # now we need to remove duplicate trials AHEM hillside :D
    previously_seen = res[0][1]
    res_final = res[0]     # sorted(set(map(lambda x: x[1], res)))
    for r in res:
        if r[1] != previously_seen:
            previously_seen = r[1]
            res_final = np.hstack((res_final, r))

    vid = np.genfromtxt(io.StringIO(''.join(vid)), delimiter='\t',
                             dtype=[('subject', '|S64'), 
                                    ('trial', 'i32'),
                                    ('eventtype', '|S64'),
                                    ('code', '|S64'),
                                    ('time', 'i32'),
                                    ('ttime', 'i32'),
                                    ('uncertainty1', 'i32')])

    # ensure our inputs contain a 'MRI_start' string.
    if pic[0][3] != 'MRI_start':
        print('ERROR: log ' + logname + ' doesnt contain an MRI_start entry!' )
        raise ValueError
    else:
        # this is the start of the fMRI run, all times are relative to this.
        mri_start = res_final[0][4]
        return pic, res_final, vid, mri_start

def find_blocks(vid, mri_start):
    """
    Takes the start time and a vid tuple list to find the relative
    block numbers, their start times, and their type (string).
    """
    blocks = []
    onsets = []
    for v in vid:

        # we will use this to search through the response files
        block_number = v[1]

        # this is maybe useless (e.g., 'vid_4')
        block_name = v[3]

        # all time in 10000s of a sec.
        block_start = (v[4] - mri_start) / 10000.0 

        # generate compressed video list
        blocks.append((block_number, block_name, block_start))
        onsets.append(block_start)

    return blocks, onsets

def find_ratings(res, pic, blk_start, blk_end, mri_start, blk_start_time):
    """
    Takes the response and picture tuple lists and the beginning of the current
    and next videos. This will search through all of the responses [vid_start
    < x < vid_end] and grab their timestamps. For each, it will find the
    corresponding picture rating and save that as an integer. 

    All times in 10,000s of a second.

    102,103 -- person responses
    104     -- MRI responses
    """

    ratings = []
    if blk_end == None:
        # find the final response number, take that as the end of our block
        trial_list = np.linspace(blk_start, res[-1][1], res[-1][1]-blk_start+1)
    else:
        # just use the beginning of the next block as our end.
        trial_list = np.linspace(blk_start, blk_end-1, blk_end-blk_start)

    # further refine our trial list to include only the first, last, and button
    # presses
    response_list = np.array(filter(lambda s: s[1] in trial_list, res))
    # if the participant dosen't respond at all, freak out.
    if len(response_list) == 0:
        ratings = np.array([5])
        return ratings, 0

    #response_first = response_list[0]
    #response_last = response_list[-1,...]
    button_pushes = np.array(filter(lambda s: '103' in s[3] or 
                                              '102' in s[3], response_list))
    response_list = np.hstack((
                    np.hstack((response_list[0,...], button_pushes)), 
                                                       response_list[-1,...]))

    # condense the trial list and add 1, as picture comes from the next trial
    trial_list = []
    for i in response_list:
        trial_list.append(i[1]+1)

    # extract the picture list
    picture_list = filter(lambda s: s[1] in trial_list, pic)

    for i, r in enumerate(response_list):

        endpoint = len(response_list)-1

        # we will use this to search through the response files
        response_number = r[1]

        # get the response time relative to the start of the 
        # (TRIAL OR SESSION??)
        if i == 0 or i == endpoint:
            response_time = (response_list[i][4] - mri_start) / 10000.0
        
        else:
            try:
                response_time = (picture_list[i][4] - mri_start) / 10000.0
            
            except:
                response_time = (response_list[i][4] - mri_start) / 10000.0

        try:
            # grab the rating string, check contents, and convert to int
            rating = picture_list[i][3]

        except:
            # use the final value
            rating = picture_list[-1][3] 
            # fill in the missing numbers with the last good recorded one
            #rating = previous_rating

        # determine the number of ratings to add (using delta time)
        n_events = 1 # default

        if i == 0:
            delta_time = (picture_list[i][4] / 10000.0) - blk_start_time

        else:
            # if we are in the middle: if i > 0 and i < endpoint:    
            # time between two picture events
            try:
                delta_time = (picture_list[i][4] - 
                              picture_list[i-1][4]) / 10000.0
            
            except:
                delta_time = (response_list[i][4] - 
                              response_list[i-1][4]) / 10000.0

        # number of TRs since last event
        n_events = np.round(delta_time / 2)
        
        # if we are at the end
        #elif i == endpoint:
            # time between final response event and final picture event
            
            # number of TRs since last event
            #n_events = np.round(delta_time / 2)

        # check that this is, in fact, a rating, and if so, add to the list
        #if rating[0:6] == 'rating':

        # ^^^ I removed this check
        if i == 0:
            rating = 5 # this is the default rating, according 2 colin
            previous_rating = copy.copy(rating)
        else:
            rating = int(rating[-1])
        for n in np.arange(n_events):
            ratings.append(previous_rating)
        # retain the current rating for the next batch
        previous_rating = copy.copy(rating)
    
    # convert to numpy array
    ratings = np.array(ratings)

    return ratings, len(button_pushes)

# def get_subj_ratings(ratings):
#     """
#     Takes a rating list of tuples and returns only the subject ratings vector,
#     for correlating with the gold standard.
#     """
#     subj_rate = []
#     for r in ratings:
#         subj_rate.append(r[2])

#     subj_rate = np.array(subj_rate)

#     return subj_rate

def find_column_data(blk_name, rating_file):
    """
    Returns the data from the column of specified file with the specified name.
    """
    # read in column names, convert to lowercase, compare with block name
    column_names = np.genfromtxt(rating_file, delimiter=',', 
                                              dtype=str)[0].tolist()
    column_names = map(lambda x: x.lower(), column_names)
    column_number = np.where(np.array(column_names) == blk_name.lower())[0]

    # read in actor ratings from the selected column, strip nans
    column_data = np.genfromtxt(rating_file, delimiter=',', 
                                              dtype=float, skip_header=2)
    
    # deal with a single value
    if len(np.shape(column_data)) == 1:
        column_data = column_data[column_number]
    # deal with a column of values
    elif len(np.shape(column_data)) == 2:
        column_data = column_data[:,column_number]
    # complain if the supplied rating_file is a dungparty
    else:
        print('*** ERROR: the file you supplied is not formatted properly!')
        raise ValueError
    # strip off NaN values
    column_data = column_data[np.isfinite(column_data)]

    return column_data

def match_lengths(a, b):
    """
    Matches the length of vector b to vector a using linear interpolation.
    """

    interp = interpolate.interp1d(np.linspace(0, len(b)-1, len(b)), b)
    b = interp(np.linspace(0, len(b)-1, len(a)))

    return b

def process_behav_data(log, assets_path, data_path, sub, trial_type):
    """
    This parses the behavioural log files for a given trial type (either 
    'vid' for the empathic-accuracy videos, or 'cvid' for the circles task.

    First, the logs are parsed into list of 'picture', 'response', and 'video'
    events, as they contain a different number of columns and carry different
    information. The 'video' list is then used to find the start of each block.

    Within each block, this script goes about parsing the ratings made by 
    the particpant using 'find_ratings'. The timing is extracted from the 
    'response' list, and the actual rating is extracted from the 'picture' 
    list.

    This is then compared with the hard-coded 'gold-standard' rating kept in 
    a column of the specified .csv file. The lengths of these vectors are 
    mached using linear interpolaton, and finally correlated. This correlation
    value is used as an amplitude modulator of the stimulus box-car. Another
    set of amplitude-modulated regressor of no interest is added using the
    number of button presses per run. 

    The relationship between these ratings are written out to a .pdf file for 
    visual inspection, however, the onsets, durations, and correlation values
    are only returned for the specified trial type. This should allow you to 
    easily write out a GLM timing file with the onsets, lengths, 
    correlations, and number of button-pushes split across trial types.
    """

    # make sure our trial type inputs are valid
    if trial_type not in ['vid', 'cvid']:
        print('trial_type input ' + str(trial_type) + ' is incorrect.')
        print('    valid: vid or cvid.')
        raise ValueError

    pic, res, vid, mri_start = log_parser(
                               os.path.join(data_path, 'behav', sub, log))
    blocks, onsets = find_blocks(vid, mri_start)
    
    durations = []
    correlations = []
    onsets_used = []
    button_pushes = []
    # format our output plot
    width, height = plt.figaspect(1.0/len(blocks))
    fig, axs = plt.subplots(1, len(blocks), figsize=(width, height*0.8))
    #fig = plt.figure(figsize=(width, height))

    for i in np.linspace(0, len(blocks)-1, len(blocks)).astype(int).tolist():

        blk_start = blocks[i][0]
        blk_start_time = blocks[i][2]

        # block end is the beginning of the next trial
        try:
            blk_end = blocks[i+1][0]
        # unless we are on the final trial of the block, then we return None
        except:
            blk_end = None

        blk_name = blocks[i][1]

        # extract ratings vector for participant and actor
        subj_rate, n_pushes = find_ratings(res, pic, blk_start, 
                                                     blk_end, mri_start,
                                                     blk_start_time)
        # = get_subj_ratings(ratings)
        gold_rate = find_column_data(blk_name, os.path.join(assets_path, 
                                                         'EA-timing.csv'))
        duration = find_column_data(blk_name, os.path.join(assets_path, 
                                                         'EA-vid-lengths.csv'))
        
        # interpolate the shorter sample to match the longer sample
        if n_pushes != 0:
            if len(subj_rate) < len(gold_rate):
                subj_rate = match_lengths(gold_rate, subj_rate)

            elif len(subj_rate) > len(gold_rate):
                gold_rate = match_lengths(subj_rate, gold_rate)
        else:
            subj_rate = np.repeat(5, len(gold_rate))

        corr = np.corrcoef(subj_rate, gold_rate)[1][0]

        # this happens when we get a flat response from the participant
        if np.isnan(corr) == True:
            corr = 0

        # add our ish to a kewl plot
        #plt.subplot(1, len(blocks), i+1, figsize=(width, height))
        axs[i].plot(gold_rate, color='black', linewidth=2)
        axs[i].plot(subj_rate, color='red', linewidth=2)
     
        # put legend in the last subplot only, for kewlness
        if i == len(blocks) -1:
            axs[i].legend(['Actor', 'Participant'], loc='best', fontsize=10, 
                                                                frameon=False)

        axs[i].set_xlim((0,len(subj_rate)-1))
        axs[i].set_xlabel('TR')

        axs[i].set_ylim((0, 10))

        # put y axis label on first subplot only, for kewlness
        if i == 0:
            axs[i].set_ylabel('Rating')

        axs[i].set_title(blk_name + ': r = ' + str(corr), size=10)

        # skip the 'other' kind of task
        if trial_type == 'vid' and blocks[i][1][0] == 'c':
            continue
        
        elif trial_type == 'cvid' and blocks[i][1][0] == 'v':
            continue
        
        # otherwise, save the output vectors
        else:
            onsets_used.append(onsets[i])
            durations.append(duration.tolist()[0])
            
            if type(corr) == int:
                correlations.append(corr)
            else:
                correlations.append(corr.tolist())
            # button pushes / minute
            button_pushes.append(n_pushes / duration.tolist()[0] / 60.0)

    fig.suptitle(log, size=10)
    fig.set_tight_layout(True)
    fig.savefig(data_path + '/ea/' + sub + '_' + log[:-4] + '.pdf')

    # this is this failing??
    print('onsets_used: ' + str(onsets_used) + ' ' + str(type(onsets_used)))
    print('durations: ' + str(durations) + ' ' + str(type(durations)))
    print('correlations: ' + str(correlations) + ' ' + str(type(correlations)))
    print('button_pushes: ' + str(button_pushes) + ' ' + str(type(button_pushes)))

    return onsets_used, durations, correlations, button_pushes

def process_functional_data(sub, data_path, code_path):
    # copy functional data into epitome-compatible structure
    try:
        niftis = filter(lambda x: 'nii.gz' in x, 
                            os.listdir(os.path.join(data_path, 'nifti', sub)))            
    
    except:
        print('ERROR: No NIFTI folder found for ' + str(sub))
        raise ValueError

    try:
        behavs = filter(lambda x: 'UCLAEmpAcc' in x, 
                            os.listdir(os.path.join(data_path, 'behav', sub)))
        if len(behavs) != 3:
            print('ERROR: Not enough BEHAV data for ' + sub)
            raise ValueError
    
    except:
        print('ERROR: No BEHAV data for ' + sub)
        raise ValueError

    # find T1s
    if os.path.isfile(os.path.join(
                      data_path, 'freesurfer', sub, 'mri/brain.mgz')) == False:
        print('ERROR: No Freesurfered T1s found for ' + str(sub))
        raise ValueError

    # find EA task
    try:
        EA_data = filter(lambda x: 'EA' in x or
                                   'Emp_Acc' in x, niftis)
        EA_data.sort()

        # remove truncated runs
        for d in EA_data:
            nifti = nib.load(os.path.join(data_path, 'nifti', sub, d))
            if nifti.shape[-1] != 277:
                EA_data.remove(d)

        # take the last three
        EA_data = EA_data[-3:]
    
    except:
        print('ERROR: No/not enough EA data found for ' + str(sub))
        raise ValueError

    # check if output already exists
    if os.path.isfile(data_path + '/ea/.' + sub + '_complete') == True:
        raise ValueError

    # MKTMP! os.path.mktmp?

    # copy data into temporary epitome structure
    # cleanup!
    
    spn.utils.make_epitome_folders('/tmp/epitome', 3)
    
    # T1: freesurfer data
    dir_i = os.path.join(os.environ['SUBJECTS_DIR'], sub, 'mri')
    os.system('mri_convert --in_type mgz --out_type nii -odt float -rt nearest '
                          '--input_volume ' + dir_i + '/brain.mgz '
                          '--output_volume /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_T1_fs.nii.gz')
    os.system('3daxialize -prefix /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_T1_brain.nii.gz '
                         '-axial /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_T1_fs.nii.gz')
    
    os.system('mri_convert --in_type mgz --out_type nii -odt float -rt nearest ' 
                          '--input_volume ' + dir_i + '/aparc+aseg.mgz ' 
                          '--output_volume /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc_fs.nii.gz')
    os.system('3daxialize -prefix /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc_brain.nii.gz ' 
                         '-axial /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc_fs.nii.gz')
    
    os.system('mri_convert --in_type mgz --out_type nii -odt float -rt nearest ' 
                          '--input_volume ' + dir_i + '/aparc.a2009s+aseg.mgz ' 
                          '--output_volume /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc2009_fs.nii.gz')
    os.system('3daxialize -prefix /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc2009_brain.nii.gz ' 
                         '-axial /tmp/epitome/TEMP/SUBJ/T1/SESS01/anat_aparc2009_fs.nii.gz')

    # functional data
    os.system('cp ' + data_path + '/nifti/' + sub + '/' + str(EA_data[0]) + 
                  ' /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/RUN01/FUNC01.nii.gz')
    os.system('cp ' + data_path + '/nifti/' + sub + '/' + str(EA_data[1]) + 
                  ' /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/RUN02/FUNC02.nii.gz')
    os.system('cp ' + data_path + '/nifti/' + sub + '/' + str(EA_data[2]) + 
                  ' /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/RUN03/FUNC03.nii.gz')
    
    # run preprocessing pipeline
    os.system('bash ' + code_path + '/spins-preproc-task.sh')

    # copy outputs into data folder
    if os.path.isdir(data_path + '/ea') == False:
        os.system('mkdir ' + data_path + '/ea' )

    # functional data
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'func_MNI-nonlin.SPINS.01.nii.gz ' +
                  data_path + '/ea/' + sub + '_func_MNI-nonlin.EA.01.nii.gz')
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'func_MNI-nonlin.SPINS.02.nii.gz ' +
                  data_path + '/ea/' + sub + '_func_MNI-nonlin.EA.02.nii.gz')
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'func_MNI-nonlin.SPINS.03.nii.gz ' +
                  data_path + '/ea/' + sub + '_func_MNI-nonlin.EA.03.nii.gz')

    # MNI space EPI mask
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'anat_EPI_mask_MNI-nonlin.nii.gz ' 
                            + data_path + '/ea/' + sub 
                            + '_anat_EPI_mask_MNI.nii.gz')

    # MNI space single-subject T1
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'reg_T1_to_TAL.nii.gz '
                            + data_path + '/ea/' + sub 
                            + '_reg_T1_to_MNI-lin.nii.gz')

    # MNI space single-subject T1
    os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
                            + 'reg_nlin_TAL.nii.gz '
                            + data_path + '/ea/' + sub 
                            + '_reg_nlin_MNI.nii.gz')

    # motion paramaters
    os.system('cat /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/PARAMS/'
                            + 'motion.SPINS.01.1D > ' +
                  data_path + '/ea/' + sub + '_motion.1D')
    os.system('cat /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/PARAMS/'
                            + 'motion.SPINS.02.1D >> ' +
                  data_path + '/ea/' + sub + '_motion.1D')
    os.system('cat /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/PARAMS/'
                            + 'motion.SPINS.03.1D >> ' +
                  data_path + '/ea/' + sub + '_motion.1D')

    # copy out QC images of registration
    #os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
    #                        + 'qc_reg_EPI_to_T1.pdf ' +
    #              data_path + '/ea/' + sub + '_qc_reg_EPI_to_T1.pdf')
    #os.system('cp /tmp/epitome/TEMP/SUBJ/FUNC/SESS01/'
    #                        + 'qc_reg_T1_to_MNI.pdf ' +
    #              data_path + '/ea/' + sub + '_qc_reg_T1_to_MNI.pdf')

    # this file denotes participants who are finished
    os.system('touch ' + data_path + '/ea/' + sub + '_complete.log')

    os.system('rm -r /tmp/epitome')

def generate_analysis_script(sub, data_path, code_path):
    """
    This writes the analysis script to replicate the methods in Harvey et al
    2013 Schizophrenia Bulletin. It expects timing files to exist (those are
    generated by 'process_behav_data').

    Briefly, this method uses the correlation between the empathic ratings of
    the participant and the actor from each video to generate an amplitude-
    modulated box-car model to be fit to each time-series. This model is
    convolved with an HRF, and is run alongside a standard boxcar. This allows
    us to detect regions that modulate their 'activation strength' with 
    empathic accruacy, and those that generally track the watching of
    emotionally-valenced videos (but do not parametrically modulate).

    Since each video is of a different length, each block is encoded as such
    in the stimulus-timing file (all times in seconds):

        [start_time]*[amplitude]:[block_length]
        30*5:12

    See '-stim_times_AM2' in AFNI's 3dDeconvolve 'help' for more.

    """
    # first, determine input functional files
    niftis = filter(lambda x: 'nii.gz' in x and sub + '_func' in x, 
                    os.listdir(os.path.join(data_path, 'ea')))
    niftis.sort()

    input_data = ''

    for nifti in niftis:
        input_data = input_data + data_path + '/ea/' + nifti + ' '

    # open up the master script, write common variables
    f = open(data_path + '/ea/' + sub + '_glm_1stlevel_cmd.sh', 'wb')
    f.write("""#!/bin/bash

# Empathic accuracy GLM for {sub}.
3dDeconvolve \\
    -input {input_data} \\
    -mask {data_path}/ea/{sub}_anat_EPI_mask_MNI.nii.gz \\
    -ortvec {data_path}/ea/{sub}_motion.1D motion_paramaters \\
    -polort 4 \\
    -num_stimts 1 \\
    -local_times \\
    -jobs 8 \\
    -x1D {data_path}/ea/{sub}_glm_1stlevel_design.mat \\
    -stim_times_AM2 1 {data_path}/ea/{sub}_block-times_ea.1D \'dmBLOCK\' \\
    -stim_label 1 empathic_accuracy \\
    -fitts {data_path}/ea/{sub}_glm_1stlevel_explained.nii.gz \\
    -bucket {data_path}/ea/{sub}_glm_1stlevel.nii.gz \\
    -cbucket {data_path}/ea/{sub}_glm_1stlevel_coeffs.nii.gz \\
    -fout \\
    -tout \\
    -xjpeg {data_path}/ea/{sub}_glm_1stlevel_matrix.jpg
""".format(input_data=input_data,data_path=data_path,sub=sub))
    f.close()

def main(base_path, tmp_path, script):
    """
    Essentially, does empathic accuracy up in this glitch.

    1) Runs functional data through a custom epitome script.
    2) Extracts block onsets, durations, and parametric modulators from
       behavioual log files collected at the scanner.
    3) Writes out AFNI-formatted timing files as well as a GLM script per
       subject.
    4) Executes this script, producing beta-weights for each subject.
    """
    # sets up relative paths (should be moved to a config.py file?)
    assets_path = base_path + '/assets'
    data_path = base_path + '/data'
    code_path = base_path + '/code'

    # get list of subjects
    subjects = spn.utils.get_subjects(data_path)

    # loop through subjects
    for sub in subjects:

        if spn.utils.subject_type(sub) == 'phantom':
            continue

        # check if output already exists
        if os.path.isfile(data_path + '/ea/' 
                                    + sub + '_complete.log') == True:
            continue
        
        try:
            process_functional_data(sub, data_path, code_path)

        except ValueError as ve:
            continue

        # get all the log files for a subject
        try:
            logs = filter(lambda x: '.log' in x and 'UCLAEmpAcc' in x, 
                                os.listdir(os.path.join(data_path, 'behav', 
                                                                    sub)))
            logs.sort()
        
        except:
            print('ERROR: No BEHAV data for ' + sub)
            continue

        # analyze each log file
        if len(logs) > 0:
            
            # open a stimulus timing file, if there are any log files
            f1 = open(data_path + '/ea/' + sub + '_block-times_ea.1D', 'wb')
            
            # record the r value and number of pushes per minute
            f2 = open(data_path + '/ea/' + sub + '_corr_push.csv', 'wb')
            f2.write('correlation,n-pushes-per-minute\n')

        for log in logs:
            on, dur, corr, push = process_behav_data(log, assets_path, 
                                                          data_path, 
                                                          sub, 
                                                          'vid')
            # write each stimulus time:
            #         [start_time]*[amplitude],[buttonpushes]:[block_length]
            #         30*5,0.002:12
            for i in range(len(on)):
                f1.write('{o:.2f}*{r:.2f},{p}:{d:.2f} '.format(o=on[i],
                                                              r=corr[i],
                                                              p=push[i],
                                                              d=dur[i]))
                f2.write('{r:.2f},{p}\n'.format(r=corr[i], p=push[i]))

            f1.write('\n') # add newline at the end of each run (up to 3 runs.)

        f1.close()
        f2.close()

        # now generate the GLM script
        generate_analysis_script(sub, data_path, code_path)

        # run each GLM script
        os.system('bash ' + data_path + '/ea/' + sub + '_glm_1stlevel_cmd.sh')

if __name__ == "__main__":
    if len(sys.argv) == 5:
        main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
