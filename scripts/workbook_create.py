######################################################################
#
# This script reads the checklist items from the latest checklist file
#   in Github (or from a local file) and generates an Azure Monitor
#   workbook in JSON format.
# 
# Last updated: February 2023
#
######################################################################

import json
import argparse
import sys
import os
import requests
import glob
import uuid

# Get input arguments
parser = argparse.ArgumentParser(description='Generate Azure Monitor workbook from Azure Review Checklist')
parser.add_argument('--checklist-file', dest='checklist_file', action='store',
                    help='You can optionally supply a JSON file containing the checklist you want to dump to the Excel spreadsheet. Otherwise it will take the latest file from Github')
parser.add_argument('--only-english', dest='only_english', action='store_true', default=False,
                    help='if checklist files are specified, ignore the non-English ones and only generate a spreadsheet for the English version (default: False)')
parser.add_argument('--find-all', dest='find_all', action='store_true', default=False,
                    help='if checklist files are specified, find all the languages for the given checklists (default: False)')
parser.add_argument('--technology', dest='technology', action='store',
                    help='If you do not supply a JSON file with the checklist, you need to specify the technology from which the latest checklist will be downloaded from Github')
parser.add_argument('--output-file', dest='output_file', action='store',
                    help='You can optionally supply an Excel file where the checklist will be saved, otherwise it will be updated in-place')
parser.add_argument('--output-path', dest='output_path', action='store',
                    help='Folder where to store the results (using the same name as the input_file)')
parser.add_argument('--blocks-path', dest='blocks_path', action='store',
                    help='Folder where the building blocks to build the workbook are stored)')
parser.add_argument('--create-arm-template', dest='create_arm_template', action='store_true',
                    default=False,
                    help='create an ARM template, additionally to the workbook JSON (default: False)')
parser.add_argument('--category', dest='category', action='store',
                    help='if the workbook should be restricted to a category containing the specified string')
parser.add_argument('--verbose', dest='verbose', action='store_true',
                    default=False,
                    help='run in verbose mode (default: False)')
args = parser.parse_args()
checklist_file = args.checklist_file
technology = args.technology

block_workbook = None
block_link = None
block_section = None
block_query = None
block_text = None

query_size = 4 # 0: medium, 1: small, 4: tiny

# Workbook building blocks
def load_building_blocks():

    # Define the blocks as global variables
    global block_workbook
    global block_link
    global block_section
    global block_query
    global block_text
    global block_invisible_parameter
    global block_arm

    # Set folder where to load from
    if args.blocks_path:
        blocks_path = args.blocks_path
        if args.verbose:
            print ("DEBUG: Setting building block folder to {0}".format(blocks_path))
    else:
        print("ERROR: please use the argument --blocks-path to specify the location of the workbook building blocks.")
        sys.exit(1)

    # Load initial workbook building block
    block_file = os.path.join(blocks_path, 'block_workbook.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_workbook = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load link building block
    block_file = os.path.join(blocks_path, 'block_link.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_link = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load itemgroup (aka section) building block
    block_file = os.path.join(blocks_path, 'block_itemgroup.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_section = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load query building block
    block_file = os.path.join(blocks_path, 'block_query.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_query = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load text building block
    block_file = os.path.join(blocks_path, 'block_text.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_text = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load invisible parameter building block
    block_file = os.path.join(blocks_path, 'block_invisible_parameter.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_invisible_parameter = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON workbook building block", block_file, "-", str(e))
        sys.exit(0)
    # Load ARM template building block
    block_file = os.path.join(blocks_path, 'block_arm.json')
    if args.verbose:
        print ("DEBUG: Loading file {0}...".format(block_file))
    try:
        with open(block_file) as f:
            block_arm = json.load(f)
    except Exception as e:
        print("ERROR: Error when opening JSON ARM template building block", block_file, "-", str(e))
        sys.exit(0)

# Function that corrects format issues in the queries stored in JSON
def fix_query_format(query_string):
    if query_string:
        query_string = str(query_string).replace('\\\\', '\\')  # Replace a double escaping inverted bar ('\\\\') through a single one ('\')
        return query_string
    else:
        return None

# Function that transforms a JSON string to be included in an ARM template
def serialize_data(workbook_string):
    if workbook_string:
        # Escape double quotes
        workbook_string = str(workbook_string).replace('"', '\"')
        # Escape escape characters
        # workbook_string = str(workbook_string).replace('\\', '\\\\')
        # Undo the scaping for the newline character (otherwise the markdown in the workbook would look wrong).
        # Note that this might impact newline characters in queries!
        # workbook_string = str(workbook_string).replace('\\\\n', '\\n')
        return workbook_string
    else:
        return None

# Main function to generate the workbook JSON
def generate_workbook(output_file, checklist_data):

    # Initialize an empty workbook
    workbook = json.loads(json.dumps(block_workbook))
    workbook_title = "## " + checklist_data['metadata']['name']
    if args.category:
        workbook_title += ' - ' + args.category[0].upper() + args.category[1:]
    workbook_title += "\n---\n\nThis workbook has been automatically generated out of the checklists in the [Azure Review Checklists repo](https://github.com/Azure/review-checklists)."
    workbook['items'][0]['content']['json'] = workbook_title

    # Decide whether we will match in the category, or subcategory, and update the corresponding variables
    if args.category:
        if args.verbose:
            print("DEBUG: creating tab list with subcategories list for categories containing the term {0}...".format(args.category))
        tab_name_field = 'subcategory'
        tab_title_list = [x["subcategory"] for x in checklist_data.get("items") if (args.category.lower() in str(x["category"]).lower())]
        tab_title_list = list(set(tab_title_list))
    else:
        if args.verbose:
            print("DEBUG: creating tab list with categories...")
        tab_name_field = 'category'
        tab_title_list = [x["name"] for x in checklist_data.get("categories")]
    if args.verbose:
        print("DEBUG: created tab list: {0}".format(str(tab_title_list)))

    # Remove the cats/subcats without queries defined
    for tab_title in tab_title_list:
        items_with_query =[x['guid'] for x in checklist_data.get("items") if ((x[tab_name_field] == tab_title) and ('graph' in x.keys()))]
        if len(items_with_query) == 0:
            if args.verbose:
                print("DEBUG: Removing tab {0} from list, it doesn't seem to have any graph queries defined".format(str(tab_title)))
            tab_title_list.remove(tab_title)

    # Bidimensional array to hold the graphs queries (x=>tab_index, y=>query_index)
    queries=[]
    for tab_title in tab_title_list:
        queries.append([])

    # Generate one tab in the workbook for each category/subcategory
    tab_id = 0
    query_id = 0
    tab_dict = {}
    
    for tab_title in tab_title_list:

        tab_dict[tab_title] = tab_id  # We will use this dict later to know where to put each query
        # Create new link
        new_link = block_link.copy()
        new_link['id'] = str(uuid.uuid4())   # RANDOM GUID
        new_link['linkLabel'] = tab_title
        new_link['subTarget'] = 'tab' + str(tab_id)
        new_link['preText'] = tab_title
        # Create new section
        new_section = block_section.copy()
        new_section['name'] = 'tab' + str(tab_id)
        new_section['conditionalVisibility']['value'] = 'tab' + str(tab_id)
        new_section['content']['items'][0]['content']['json'] = "## " + tab_title
        new_section['content']['items'][0]['name'] = 'tab' + str(tab_id) + 'title'
        # Add link and query to workbook
        # if args.verbose:
        #     print()
        #     print ("DEBUG: Adding link: {0}".format(json.dumps(new_link)))
        #     print ("DEBUG: Adding section: {0}".format(json.dumps(new_section)))
        #     print("DEBUG: Workbook so far: {0}".format(json.dumps(workbook)))
        workbook['items'][3]['content']['links'].append(new_link.copy())   # I am getting crazy with Python variable references :(
        # Add section to workbook
        new_new_section=json.loads(json.dumps(new_section.copy()))
        workbook['items'].append(new_new_section)
        tab_id += 1

    if args.verbose:
        print("DEBUG: tab dictionary generated: {0}".format(str(tab_dict)))

    # For each checklist item, add a query to the workbook
    for item in checklist_data.get("items"):
        # We will append this to every query
        query_suffix = ' | extend onlyFailed = {OnlyFailed:label} | where compliant == 0 or not (onlyFailed == 1) | project-away onlyFailed'
        # Read variables from JSON
        guid = item.get("guid")
        tab = item.get(tab_name_field)
        text = item.get("text")
        description = item.get("description")
        severity = item.get("severity")
        link = item.get("link")
        training = item.get("training")
        graph_query = fix_query_format(item.get("graph"))
        if graph_query and (tab in tab_title_list):
            if args.verbose:
                print("DEBUG: adding sections to workbook for ARG query '{0}', length of query is {1}".format(str(graph_query), str(len(str(graph_query)))))
            # Create new text
            new_text = block_text.copy()
            new_text['name'] = 'querytext' + str(query_id)
            new_text['content']['json'] = text
            if link:
                new_text['content']['json'] += ". Check [this link](" + link + ") for further information."
            if training:
                new_text['content']['json'] += ". [This training](" + training + ") can help to educate yourself on this."
            # Create new query
            new_query = block_query.copy()
            new_query['name'] = 'query' + str(query_id)
            new_query['content']['query'] = graph_query + query_suffix
            new_query['content']['size'] = query_size
            # Add text and query to the workbook
            tab_id = tab_dict[tab] + len(block_workbook['items'])
            if args.verbose:
                print ("DEBUG: Adding text and query to tab ID {0} ({1})".format(str(tab_id), tab))
                print ("DEBUG: Workbook object name is {0}".format(workbook['items'][tab_id]['name']))
            new_new_text = json.loads(json.dumps(new_text.copy()))
            new_new_query = json.loads(json.dumps(new_query.copy()))
            workbook['items'][tab_id]['content']['items'].append(new_new_text)
            workbook['items'][tab_id]['content']['items'].append(new_new_query)
            # Add query to the query array
            tab_id = tab_title_list.index(tab)
            queries[tab_id].append(graph_query)
            # Increment query counter
            query_id += 1

    # Add invisible parameters to the workbook with number of success and total items
    if args.verbose:
        print("DEBUG: Adding hidden parameters to workbook main section for {0} tabs...".format(str(len(queries))))
    tab_id = 0
    for tab_title in tab_title_list:
        print("DEBUG: Adding hidden parameters for tab {0}, with {1} queries".format(str(tab_id), str(len(queries[tab_id]))))
        # We shouldn't have any tabs without queries, but still...
        if len(queries[tab_id]) > 0:
            query_id = 0
            summary_query = queries[tab_id][query_id]
            while query_id + 1 < len(queries[tab_id]):
                query_id += 1
                summary_query += "| union ({0})".format(queries[tab_id][query_id])
            summary_query += '| summarize Total = count()'
            new_parameter = block_invisible_parameter.copy()
            new_parameter['query'] = summary_query
            new_parameter['name'] = 'Section' + str(tab_id) + 'Total'
            new_new_parameter = json.loads(json.dumps(new_parameter.copy()))
            if args.verbose:
                print("DEBUG: adding hidden parameter {0}".format(json.dumps(new_new_parameter)))
            workbook['items'][2]['content']['parameters'].append(new_new_parameter)
            # Move to the next query
            tab_id += 1

    # Dump the workbook to the output file or to console, if there was any query in the original checklist
    if args.verbose:
        print ("DEBUG: Starting output process...")
    if query_id > 0:
        if output_file:
            # Dump workbook JSON into a file
            workbook_string = json.dumps(workbook, indent=4)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(workbook_string)
                f.close()
            # Create ARM template (optionally, if specified in the parameters)
            if args.create_arm_template:
                arm_output_file = os.path.splitext(output_file)[0] + '_template.json'
                if args.verbose:
                    print ("DEBUG: Creating ARM template in file {0}...".format(arm_output_file))
                block_arm['parameters']['workbookDisplayName']['defaultValue'] = checklist_data['metadata']['name']
                if args.category:
                    block_arm['parameters']['workbookDisplayName']['defaultValue'] += ' - ' + args.category[0].upper() + args.category[1:]
                block_arm['resources'][0]['properties']['serializedData'] = serialize_data(workbook_string)
                arm_string = json.dumps(block_arm, indent=4)
                with open(arm_output_file, 'w', encoding='utf-8') as f:
                    f.write(arm_string)
                    f.close()
        else:
            print(workbook_string)
    else:
        print("INFO: sorry, the analyzed checklist did not contain any graph query")

def get_output_file(checklist_file_or_url, is_file=True):
    if is_file:
        output_file = os.path.basename(checklist_file_or_url)
    else:
        output_file = checklist_file_or_url.split('/')[-1]
    if args.output_file:
        return args.output_file
    elif args.output_path:
        # Get filename without path and extension
        output_file = os.path.join(args.output_path, output_file)
        # If category specified, add to output file name
        if args.category:
            return os.path.splitext(output_file)[0] + '_' + str(args.category).lower() + '_workbook.json'
        else:
            return os.path.splitext(output_file)[0] + '_workbook.json'
    else:
        output_file = None


########
# Main #
########

# First thing of all, load the building blocks
load_building_blocks()
if args.verbose:
    print ("DEBUG: building blocks variables intialized:")
    print ("DEBUG:    - Workbook: {0}".format(str(block_workbook)))
    print ("DEBUG:    -    Number of items: {0}".format(str(len(block_workbook['items']))))
    print ("DEBUG:    - Link: {0}".format(str(block_link)))
    print ("DEBUG:    - Query: {0}".format(str(block_query)))

# Download checklist or process from local file
if checklist_file:
    checklist_file_list = checklist_file.split(" ")
    # Take only the English versions of the checklists (JSON files)
    checklist_file_list = [file[:-8] + '.en.json' for file in checklist_file_list if (os.path.splitext(file)[1] == '.json')]
    # Remove duplicates
    checklist_file_list = list(set(checklist_file_list))
    # Go over the list(s)
    for checklist_file in checklist_file_list:
        if args.verbose:
            print("DEBUG: Opening checklist file", checklist_file)
        # Get JSON
        try:
            # Open file
            with open(checklist_file) as f:
                checklist_data = json.load(f)
            # Set output file variable
            output_file = get_output_file(checklist_file, is_file=True)
            # Generate workbook
            generate_workbook(output_file, checklist_data)
        # If error, just continue
        except Exception as e:
            print("ERROR: Error when processing JSON file", checklist_file, "-", str(e))
            # sys.exit(0)
else:
    # If no input files specified, fetch the latest from Github...
    if technology:
        checklist_url = "https://raw.githubusercontent.com/Azure/review-checklists/main/checklists/" + technology + "_checklist.en.json"
    else:
        checklist_url = "https://raw.githubusercontent.com/Azure/review-checklists/main/checklists/lz_checklist.en.json"
    if args.verbose:
        print("DEBUG: Downloading checklist file from", checklist_url)
    response = requests.get(checklist_url)
    # If download was successful
    if response.status_code == 200:
        if args.verbose:
            print ("DEBUG: File {0} downloaded successfully".format(checklist_url))
        try:
            # Deserialize JSON to object variable
            checklist_data = json.loads(response.text)
        except Exception as e:
            print("Error deserializing JSON content: {0}".format(str(e)))
            sys.exit(1)
        # Set output files
        output_file = get_output_file(checklist_url, is_file=False)
        # Generate workbook
        generate_workbook(output_file, checklist_data)

