#!/usr/bin/env python

# Assumptions: a read only maps to one amplicon (not overlapping with another).

import sys
from argparse import ArgumentParser
import logging
from visualise import make_html

DEFAULT_WEBASSETS = 'package'

def parseArgs():
    parser = ArgumentParser(
        description = 'Count methylation patterns in bismark output')
    parser.add_argument(
        '--dump_reads', metavar='FILE', type=str,
        help='dump the read methylation information to FILE')
    parser.add_argument(
        'bismark_file', metavar='BISMARK_FILE', type=str,
        help='input bismark file')
    parser.add_argument(
        '--count_thresh', metavar='THRESH', type=int, default=0,
        help='only display methylation patterns with at least THRESH number of matching reads')
    parser.add_argument(
        '--amplicons', metavar='AMPLICONS_FILE', type=str, required=True,
        help='file containing amplicon information in TSV format')
    parser.add_argument('--logfile', metavar='FILENAME', type=str, required=True,
        help='log progress in FILENAME')
    parser.add_argument('--html', metavar='FILENAME', type=str, required=True,
        help='save visualisation in html FILENAME')
    parser.add_argument('--webassets', choices=('package', 'local', 'online'), type=str,
        default=DEFAULT_WEBASSETS,
        help='location of assets used by output visualisation web page, defaults to {}'.format(DEFAULT_WEBASSETS))
    return parser.parse_args()

def encode_methyl(char):
    "convert a methylation state to a binary digit"
    try:
        return { 'z' : 0, 'Z' : 1 }[char]
    except KeyError:
        exit('unexpected methylation state ' + char)

def pretty_state(unique_sites, cpg_sites):
    unique_index = 0
    cpg_index = 0 
    result = ''
    while unique_index < len(unique_sites):
        if cpg_index < len(cpg_sites):
            if unique_sites[unique_index] == cpg_sites[cpg_index].pos:
                result += str(cpg_sites[cpg_index].methyl_state)
                unique_index += 1
                cpg_index += 1
            else:
                result += '-'
                unique_index += 1
        else:
            result += '-'
            unique_index += 1
    return result

class CPG_site(object):
    def __init__(self, pos, methyl_state):
        # pos is an integer
        self.pos = pos
        # methyl_state is '0' (off) or '1' (on)
        self.methyl_state = methyl_state

    def __cmp__(self, other):
        return cmp(self.pos, other.pos)

    def __str__(self):
        return "({0}, {1})".format(self.pos, self.methyl_state)

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        return self.pos == other.pos and self.methyl_state == other.methyl_state

    def __hash__(self):
        return hash((self.pos, self.methyl_state))

class Read(object):
    def __init__(self, chr, cpg_sites):
        self.chr = chr
        # cpg_sites are encoded and lists of pairs of (pos, methyl)
        # this is a methylation pattern
        self.cpg_sites = cpg_sites

class Amplicon(object):
    def __init__(self, start, end, start_trim, end_trim, name):
        self.start = start
        self.end = end
        self.start_trim = start + start_trim
        self.end_trim = end - end_trim
        self.name = name

    # the ordering of amplicons is determined by their start and end positions
    # they are assumed to be non-overlapping
    def __cmp__(self, other):
        return cmp((self.start, self.end), (other.start, other.end))

def intesect_cpg_sites_amplicon(cpg_sites, amplicon):
    '''Compute the intersection of a list of sorted (ascending) cpg sites with
    the trimmed part of an amplicon. If the intersection is empty then
    the result is an empty list. Otherwise it is a list of sorted cpg sites
    that actually lie within the trimmed amplicon.'''

    return [ cpg for cpg in cpg_sites
                 if cpg.pos >= amplicon.start_trim and
                    cpg.pos <= amplicon.end_trim ]
 
def main():
    args = parseArgs()

    logging.basicConfig(filename=args.logfile,
                        level=logging.DEBUG,
                        filemode='w',
                        format='%(asctime)s %(message)s',
                        datefmt='%m/%d/%Y %H:%M:%S')
    logging.info('program started')
    logging.info('command line: {0}'.format(' '.join(sys.argv)))

    reads = {}

    # collect the list of CPG sites for each read id 
    # the input file has one CPG site per line, identified to a given read id
    # Bismark file has format:
    # READ_ID STRAND(+/-) CHROMOSOME POSITION METHYL_STATE(z/Z)
    # Each READ_ID can appear multiple times, once for each position with
    # a corresponding methylation state. We collect all (pos, methyl_state)
    # pairs together for each read_id. 
    with open(args.bismark_file) as file:
        next(file) # skip the header
        for line in file:
            parts = line.split()
            read_id, _strand, chr, pos, methyl = parts[0:5]
            # convert methylation state to binary digit 
            cpg_site = CPG_site(int(pos), encode_methyl(methyl))
            # reads with the same id must be in the same chr
            if read_id in reads:
                reads[read_id].cpg_sites.append(cpg_site)
            else:
                reads[read_id] = Read(chr, [cpg_site])

    # mapping from amplicon name to chromosome name
    amplicon_chromosomes = {}

    # Amplicons are represented as:
    # CHROMOSOME START_POS END_POS NAME SIZE TRIM_START TRIM_END

    # mapping from chr name to list of amplicons
    # each amplicon is represented as (start, end, name)
    # We assume the amplicons are not overlapping.

    # keep a record of the amplicon names in the order that they appeared
    # in the input file, so we can render them in the same order in 
    # the visualisation.
    amplicon_names = []
    amplicons = {}
    with open(args.amplicons) as file:
        for line in file:
            parts = line.split()
            chr, start, end, name, size, trim_start, trim_end = parts[:7]
            amplicon = Amplicon(int(start), int(end), int(trim_start), int(trim_end), name)
            amplicon_names.append(name)
            if chr in amplicons:
                amplicons[chr].append(amplicon)
            else:
                amplicons[chr] = [amplicon]
            amplicon_chromosomes[name] = chr

    # sort the amplicon entries based on their coordinates
    for chr in amplicons:
        amplicons[chr].sort()

    if args.dump_reads != None:
        with open(args.dump_reads, 'w') as file:
            read_list = []
            for read_id, read in reads.items():
                read_list.append((read.cpg_sites, read_id))
 
            for cpg_sites, id in sorted(read_list):
                file.write('{0} {1}\n'.format(str(cpg_sites), id))

    # We want to associate each amplicon with all the different methylation patterns
    # which it contains, and have a counter for each one. The cpg_sites represents
    # a particular methylation pattern.
    # amplicon -> cpg_sites -> count
    methyl_state_counts = {}

    for read_id, read in reads.items():
        intersection = []
        if read.chr in amplicons:
           # sort cpg sites based on their position
           cpg_sites = sorted(read.cpg_sites)

           for amplicon in amplicons[read.chr]:
               intersection = tuple(intesect_cpg_sites_amplicon(cpg_sites, amplicon))
               if intersection:
                   #methyl_states.append(amplicon.name, tuple(cpg_sites))
                   if amplicon.name in methyl_state_counts:
                       this_amplicon_info = methyl_state_counts[amplicon.name]
	               if intersection in this_amplicon_info:
		           this_amplicon_info[intersection] += 1
	               else:
		           this_amplicon_info[intersection] = 1
	           else:
	               methyl_state_counts[amplicon.name] = { intersection : 1 }

                   # stop searching for an amplicon if we find a non-empty intersection
                   # we assume a read intersects only one amplicon
                   break

        if not intersection:
	    logging.info("read {0} in chromosome {1} not in any amplicon".format(read_id, read.chr)) 

    # map each amplicon name to a list of its unique methylation sites (chr positions)
    amplicon_unique_sites = {}
    result = []
    for amplicon in methyl_state_counts:
        # compute the set of unique CPG sites for this amplicon
        unique_sites = set()
        for cpg_sites in methyl_state_counts[amplicon].keys():
            unique_sites.update([site.pos for site in cpg_sites])
        if len(unique_sites) > 0:
            # sort the unique CPG sites into ascending order of position
            unique_sites = sorted(unique_sites)
            amplicon_unique_sites[amplicon] = unique_sites
            start_pos = unique_sites[0]
            end_pos = unique_sites[-1]
            for cpg_sites, count in methyl_state_counts[amplicon].items():
                if count >= args.count_thresh:
                    binary = pretty_state(unique_sites, cpg_sites)
                    binary_raw = str(cpg_sites)
                    chr = amplicon_chromosomes[amplicon]
                    result.append((amplicon, chr, start_pos, end_pos, binary, count, binary_raw))

    print('\t'.join(["<amplicon ID>", "<chr>", "<Base position start/CpG start>",
          "<Base position end/CpG end>", "<Methylation pattern>", "<count>", "<raw cpg sites>"]))

    json_dict = {}
 
    # unique number for each amplicon
    unique_id = 0

    for amplicon, chr, start, end, binary, count, binary_raw in sorted(result):
        print('\t'.join([amplicon, chr, str(start), str(end), binary, str(count), binary_raw]))
        pattern_dict = { 'count': count, 'methylation': to_json_pattern(binary) }
        if amplicon in json_dict:
            amplicon_dict = json_dict[amplicon]
            amplicon_dict['patterns'].append(pattern_dict)
        else:
            try:
                unique_sites = amplicon_unique_sites[amplicon]
            except KeyError:
                unique_sites = []
            amplicon_dict = { 'unique_id': unique_id
                            , 'amplicon': amplicon
                            , 'sites': unique_sites
                            , 'chr': chr
                            , 'start': start
                            , 'end': end
                            , 'patterns': [pattern_dict] }
            json_dict[amplicon] = amplicon_dict
            unique_id += 1

    make_html(args, amplicon_names, json_dict)


def to_json_pattern(binary):
    char_to_int = { '0': 0, '1': 1, '-': 2 }
    return [ char_to_int[c] for c in binary ]

if __name__ == '__main__':
    main()
