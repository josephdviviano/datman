#!/usr/bin/env python
"""
This run CIVET on stuff

Usage:
  run-proc-CIVET.py [options] <inputdir> <targetdir>

Arguments:
    <inputpath>     Path to input directory (usually a project directory inside /data-2.0)
    <targetdir>     Path to directory that will contain CIVET inputs (links) and outputs
    <prefix>`       Prefix for CIVET input (see details)    `

Options:
  --multimodal             Use the T1W, T2W and PD images in pipeline (default = use only T1W)
  --1-Telsa                Use CIVET options for 1-Telsa data (default = 3T options)
  --checklist FILE		   Filename of the checklist file (default = <targetdir>/CIVETchecklist.csv
  --T1-tag				   Tag in filename that indicates it's a T1 (default = "_T1_")
  --T2-tag				   Tag in filename that indicates it's a T2 (default = "_T2_")
  --PD-tag				   Tag in filename that indicates it's a PD (default = "_PD_")
  -v,--verbose             Verbose logging
  --debug                  Debug logging in Erin's very verbose style
  -n,--dry-run             Dry run

DETAILS
Requires that CIVET module has been loaded.
"""
from docopt import docopt
import pandas as pd
import datman as dm
import datman.utils
import datman.scanid
import os.path
import sys

MULTIMODEL = False
ONETESLA = False
VERBOSE = False
VVERBOSE = False
DRYRUN  = False
DEBUG   = False

def main():
    global VERBOSE
    global VVERBOSE
    global DRYRUN
    global DEBUG
    global ONETESLA
    global MULTIMODEL
    arguments    = docopt(__doc__)
    inputpath    = arguments['<inputpath>']
    targetdir    = arguments['<targetdir>']
    prefix       = arguments['<prefix>']
    MULTIMODEL   = arguments['--mulitmodal']
    ONETESLA     = arguments['--1-Telsa']
    VVERBOSE     = arguments['--vverbose']
    VERBOSE      = arguments['--verbose']
    DEBUG        = arguments['--debug']
    DRYRUN       = arguments['--dry-run']

    ## make the civety directory if it doesn't exist
    civet_in    = os.path.normpath(targetdir+'/input/')
    civet_out   = os.path.normpath(targetdir+'/output/')
    civet_logs  = os.path.normpath(targetdir+'/logs/')
    dm.utils.makedirs(civet_in)
    dm.utils.makedirs(civet_out)
    dm.utils.makedirs(civet_logs)
	
	## if the checklist exists - open it, if not - create the dataframe
	checklistfile = os.path.normpath(targetdir+'/CIVETchecklist.csv')
	if os.file.exits(checklistfile):
		checklist = pd.read_table(lookup_table, sep='\s+', dtype=str, comment='#')
	else:
		cols = ["id", "mnc_t1", "civetid", "civet_run", "qc_run", "qc_rator", "qc_rating", "notes"]
		if MULTIMODEL:
			cols.insert(2,"mnc_t2")
			cols.insert(2,"mnc_pd")
		checklist = pd.DataFrame(columns = cols)
	
    ## find those subjects in input who have not been processed yet
    subids_in_mnc = dm.utils.get_subjects(os.path.normpath(inputpath))    
    subids_in_mnc = [ v for v in subids_in_mnc if "PHA" not in v ] ## remove the phantoms from the list
	newsubs = list(set(subids_in_mnc) - set(checklist.id))
	newsubs_df = pd.DataFrame(columns = cols, index = newsubs)
	newsubs_df.id = newsubs
	checklist = checklist.append(newsubs_df)
			
    # need to find the t1 weighted scan and update the checklist
	for i in len(checklist):
		#if civet name not in checklist add link to checklist
		if pd.isnull(checklist['civetid'][i]): 
			checklist['civetid'][i] = checklist.id[i].replace(prefix,'').replace('_',"")
		#if link doesn't exist
		t1_link = os.path.join(civet_in, checklist['civetid'][i] + '_t1.mnc')	
		if os.path.exists(t1_link)==False:
			mncdir = os.path.join(inputpath,checklist['id'][i] 
			#if mnc name not in checklist
			if pd.isnull(checklist['mni_t1'][i]):		
				mncfiles = []
				for fname in os.listdir(mncdir):
					if 'T1' in fname:
						mncfiles.append(fname)
				if len(mncfiles) == 1:
					checklist['mni_t1'][i] = mncfiles[0]
				elif len(mincT1) > 1:
					checklist['notes'][i] = "> 1 T1W image found, need to pick bext one"
				elif len(mincT1) < 1:
					checklist['notes'][i] = "No T1W image found."
			# make the link
			if pd.isnull(checklist['mni_t1'][i])==False:
				mncpath = os.path.join(mncdir,checklist['mni_t1'][i])
				relpath = os.path.relpath(mncpath,os.path.dirname(t1_link))
				log("linking {} to {}".format(relpath, t1_link))
				if not DRYRUN:
					os.symlink(relpath, t1_link)
			
	## now checkoutputs to see if any of them have been run
		#if yes update spreadsheet
		#if no add to subjectlist to run
	toruntoday = []
	for i in len(checklist):
		if checklist['civet_run']=="Y":
			continue
		subid = checklist['civetid'][i]
		thicknessdir = os.path.join(civet_out,subid,'thickness')
		if os.path.exists(thicknessdir)== False:
			toruntoday.append(subid)
		else if len(os.listdir(thicknessdir)) == 5:
				checklist['civet_run'] = "Y"
			 else :
				checklist['notes'] = "something was bad with CIVET :("
	
    ## write the subids to a file if there are more than ten
    if len(toruntoday) > 10:
		# write them to file fileidrun_<date>.txt
	CIVETcmd = 'CIVET_Processing_Pipeline' + ' -sourcedir ' + civet_in + ' -targetdir ' + civet_out + ' -prefix ' + prefix 
	CIVETcmd = CIVETcmd + ' -run -animal -lobe_atlas -resample-surfaces -granular -VBM -thickness tlink 20 -queue main.q'
	
    ##run CIVET on those subjects
    	CIVET_Processing_Pipeline -sourcedir input -targetdir output -prefix ${prefix} -id-file file_ids.txt -run -animal -lobe_atlas -resample-surfaces -granular -VBM -thickness tlink 20 -queue main.q -3Tesla -N3-distance 75
    	touch .doneCIVET

    ## find those subjects who were run but who have no qc pages made

    ##run CIVET QC
    CIVET_QC_Pipeline -sourcedir input -targetdir output -prefix ${prefix} -id-file file_ids.txt
    ##
    if [ ! -e /output/QC/civet_${prefix}.html ]
    then
    	echo "QC ERROR. YOU FAILED."
    	sleep 5
    	echo "kidding CIVET failed"
    fi
    ## do some logging stuff
