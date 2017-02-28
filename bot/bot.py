#! /usr/bin/python
"""
    This Bot will use a provided Spark Account (identified by the Developer Token)
    and create a webhook to receive all messages sent to the account.   You will
    specify a set of command words that the Bot will "listen" for.  Any other message
    sent to the bot will result in the help message being sent back.

    The bot is designed to be deployed as a Docker Container, and can run on any
    platform supporting Docker Containers.  Mantl.io is one example of a platform
    that can be used to run the bot.

    There are several pieces of information needed to run this application.  These
    details can be provided as Environment Variables to the application.  The Spark
    token and email address can alternatively be provided/updated via an POST request to /config.

    If you are running the python application directly, you can set them like this:

    # Details on the Cisco Spark Account to Use
    export SPARK_BOT_EMAIL=myhero.demo@domain.com
    export SPARK_BOT_TOKEN=adfiafdadfadfaij12321kaf

    # Public Address and Name for the Spark Bot Application
    export SPARK_BOT_URL=http://myhero-spark.mantl.domain.com
    export SPARK_BOT_APP_NAME="imapex bot"

    If you are running the bot within a docker container, they would be set like this:
    docker run -it --name sparkbot \
    -e "SPARK_BOT_EMAIL=myhero.demo@domain.com" \
    -e "SPARK_BOT_TOKEN=adfiafdadfadfaij12321kaf" \
    -e "SPARK_BOT_URL=http://myhero-spark.mantl.domain.com" \
    -e "SPARK_BOT_APP_NAME='imapex bot'" \
    sparkbot

    In cases where storing the Spark Email and Token as Environment Variables could
    be a security risk, you can alternatively set them via a REST request.

    curl -X POST http://localhost:5000/config \
        -d "{\"SPARK_BOT_TOKEN\": \"<TOKEN>\", \"SPARK_BOT_EMAIL\": \"<EMAIL>"}"

    You can read the configuration details with this request

    curl http://localhost:5000/config

"""

from flask import Flask, request
from ciscosparkapi import CiscoSparkAPI
import os
import sys
import json
import requests
import re

# Create the Flask application that provides the bot foundation
app = Flask(__name__)


# ToDos:
    # todo last modified (calculate duration)
    # todo create date (calculate duration)
    # todo RMAs
    # todo device serial
    # todo invite cse to room
    # todo invite by email
    # todo last note created with "action plan" or "next steps" in note detail
    # todo feedback
    # todo add RMA API functions
    # todo monitor case and alert on changes


# The list of commands the bot listens for
# Each key in the dictionary is a command
# The value is the help message sent for the command
commands = {
    "/title": "Get title for TAC case number provided, if none provided will look in room name.",
    "/description": "Get problem description for the TAC case number provided, if none provided will look in the room name.",
    "/owner": "Get case owner for TAC case number provided, if none provided will look in room name.",
    "/contract": "Get contract number associated with the case number provided, if none provided will look in the room name.",
    "/customer": "Get customer contact info for the TAC case number provided, if none provided will look in room name.",
    "/status": "Get status and severity for the TAC case number provided, if none provided will look in the room name",
    "/rma": "Get list of RMAs associated with TAC case number provided, if none provided will look in the room name",
    "/echo": "Reply back with the same message sent.",
    "/help": "Get help.",
	"/test": "Print test message."
}


# Not strictly needed for most bots, but this allows for requests to be sent
# to the bot from other web sites.  "CORS" Requests
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type,Authorization,Key')
    response.headers.add('Access-Control-Allow-Methods',
                         'GET,PUT,POST,DELETE,OPTIONS')
    return response


# Entry point for Spark Webhooks
@app.route('/', methods=["POST"])
def process_webhook():
    # Check if the Spark connection has been made
    if spark is None:
        sys.stderr.write("Bot not ready.  \n")
        return "Spark Bot not ready.  "

    post_data = request.get_json(force=True)
    # Uncomment to debug
    # sys.stderr.write("Webhook content:" + "\n")
    # sys.stderr.write(str(post_data) + "\n")

    # Take the posted data and send to the processing function
    process_incoming_message(post_data)
    return ""


# Config Endpoint to set Spark Details
@app.route('/config', methods=["GET", "POST"])
def config_bot():
    if request.method == "POST":
        post_data = request.get_json(force=True)
        # Verify that a token and email were both provided
        if "SPARK_BOT_TOKEN" not in post_data.keys() or "SPARK_BOT_EMAIL" not in post_data.keys():
            return "Error: POST Requires both 'SPARK_BOT_TOKEN' and 'SPARK_BOT_EMAIL' to be provided."

        # Setup Spark
        spark_setup(post_data["SPARK_BOT_EMAIL"], post_data["SPARK_BOT_TOKEN"])

    # Return the config detail to API requests
    config_data = {
        "SPARK_BOT_EMAIL": bot_email,
        "SPARK_BOT_TOKEN": spark_token,
        "SPARK_BOT_URL": bot_url,
        "SPARKBOT_APP_NAME": bot_app_name
    }
    config_data["SPARK_BOT_TOKEN"] = "REDACTED"     # Used to hide the token from requests.
    return json.dumps(config_data)


# Quick REST API to have bot send a message to a user
@app.route("/hello/<email>", methods=["GET"])
def message_email(email):
    """
    Kickoff a 1 on 1 chat with a given email
    :param email:
    :return:
    """
    # Check if the Spark connection has been made
    if spark is None:
        sys.stderr.write("Bot not ready.  \n")
        return "Spark Bot not ready.  "

    # send_message_to_email(email, "Hello!")
    spark.messages.create(toPersonEmail=email, markdown="Hello!")
    return "Message sent to " + email


# Health Check
@app.route("/health", methods=["GET"])
def health_check():
    """
    Notify if bot is up
    :return:
    """
    return "Up and healthy"


# REST API for room creation
@app.route("/create/<provided_case_number>/<email>", methods=["GET"])
def create(provided_case_number, email):
    """
    Kickoff a 1 on 1 chat with a given email
    :param email:
    :return:
    """
    # Check if the Spark connection has been made
    if spark is None:
        sys.stderr.write("Bot not ready.  \n")
        return "Spark Bot not ready.  "

    # Check if provided case number is valid
    case_number = get_case_number(provided_case_number)
    if case_number:
        # Get person ID for email provided
        person_id = get_person_id(email)
        if person_id:
            #sys.stderr.write("Person ID for email ("+email+"): "+person_id+"\n")

            # Check if room already exists for case and  user
            room_id = room_exists_for_user(case_number, email)
            if room_id:
                message = "Room already exists with  "+case_number+" in the title and "+email+" already a member.\n"
                sys.stderr.write(message)
                sys.stderr.write("roomId: "+room_id+"\n")
            else:
                # Create the new room
                room_id = create_room(case_number)
                message = "Created roomId: "+room_id+"\n"
                sys.stderr.write(message)
        
                # Add user to the room
                membership_id = create_membership(person_id, room_id)
                membership_message = email+" added to the room.\n"
                sys.stderr.write(membership_message)
                sys.stderr.write("membershipId: "+membership_id)
                message = message+membership_message
        
            # Print Welcome message to room
            spark.messages.create(roomId=room_id, markdown=send_help(False))
            welcome_message = "Welcome message (with help command) sent to the room.\n"
            sys.stderr.write(welcome_message)
            message = message+welcome_message
        else:
            message = "No user found with the email address: "+email
            sys.stderr.write(message)
    else: 
        message = provided_case_number+" is not a valid case number"
        sys.stderr.write(message)
    
    return message


# Function to Setup the WebHook for the bot
def setup_webhook(name, targeturl):
    # Get a list of current webhooks
    webhooks = spark.webhooks.list()

    # Look for a Webhook for this bot_name
    # Need try block because if there are NO webhooks it throws an error
    try:
        for h in webhooks:  # Efficiently iterates through returned objects
            if h.name == name:
                sys.stderr.write("Found existing webhook.  Updating it.\n")
                wh = spark.webhooks.update(webhookId=h.id, name=name, targetUrl=targeturl)
                # Stop searching
                break
        # If there wasn't a Webhook found
        if wh is None:
            sys.stderr.write("Creating new webhook.\n")
            wh = spark.webhooks.create(name=name, targetUrl=targeturl, resource="messages", event="created")
    except:
        sys.stderr.write("Creating new webhook.\n")
        wh = spark.webhooks.create(name=name, targetUrl=targeturl, resource="messages", event="created")

    return wh


# Function to take action on incoming message
def process_incoming_message(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message = spark.messages.get(message_id)
    # Uncomment to debug
    # sys.stderr.write("Message content:" + "\n")
    # sys.stderr.write(str(message) + "\n")

    # First make sure not processing a message from the bot
    if message.personEmail in spark.people.me().emails:
        # Uncomment to debug
        # sys.stderr.write("Message from bot recieved." + "\n")
        return ""

    # Log details on message
    sys.stderr.write("Message from: " + message.personEmail + "\n")

    # Find the command that was sent, if any
    command = ""
    for c in commands.items():
        if message.text.find(c[0]) != -1:
            command = c[0]
            sys.stderr.write("Found command: " + command + "\n")
            # If a command was found, stop looking for others
            break

    reply = ""
    # Take action based on command
    # If no command found, send help
    if command in ["", "/help"]:
        reply = send_help(post_data)
    elif command in ["/echo"]:
        reply = send_echo(message)
    elif command in ["/test"]:
        reply = send_test()
    elif command in ["/title"]:
        reply = send_title(post_data)
    elif command in ["/owner"]:
        reply = send_owner(post_data)
    elif command in ["/description"]:
        reply = send_description(post_data)
    elif command in ["/contract"]:
        reply = send_contract(post_data)
    elif command in ["/customer"]:
        reply = send_customer(post_data)
    elif command in ["/status"]:
        reply = send_status(post_data)
    elif command in ["/rma"]:
        reply = send_rma_numbers(post_data)

    # send_message_to_room(room_id, reply)
    spark.messages.create(roomId=room_id, markdown=reply)


#
# Command functions
#

# Returns case title for provided case number
def send_title(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/title", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR " + str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR " + str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    # Get the title from the case details
    case_title = case_details['RESPONSE']['CASES']['CASE_DETAIL']['TITLE']
    message = "Title for SR {} is: {}".format(case_number, case_title)
    return message


# Returns case description for provided case number
def send_description(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/description", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR " + str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR " + str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    # Get the cescription from the case details
    case_description = case_details['RESPONSE']['CASES']['CASE_DETAIL']['PROBLEM_DESC']
    message = "Problem description for SR {} is: <br>{}".format(case_number, case_description)
    return message


# Returns the owner of the TAC case number provided
def send_owner(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/owner", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR " + str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR " + str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    #Get the owner from the case details
    case_owner_id = case_details['RESPONSE']['CASES']['CASE_DETAIL']['OWNER_USER_ID']
    case_owner_first = case_details['RESPONSE']['CASES']['CASE_DETAIL']['OWNER_FIRST_NAME']
    case_owner_last = case_details['RESPONSE']['CASES']['CASE_DETAIL']['OWNER_LAST_NAME']
    case_owner_email = case_details['RESPONSE']['CASES']['CASE_DETAIL']['OWNER_EMAIL_ADDRESS']
    message = "Case owner for SR {} is: {} {} ({})". format(case_number, case_owner_first, case_owner_last, case_owner_email)
    return message


# Returns contract number for provided case number
def send_contract(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/contract", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR " + str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR " + str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    # Get the contract from the case details
    case_contract = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTRACT_ID']
    message = "The contract number used to open SR {} is: {}".format(case_number, case_contract)
    return message


# Returns the owner of the TAC case number provided
def send_customer(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/customer", message_in.text)

    # Check if case number is found in message content
    if content:
        case_number = get_case_number(content)
        if case_number:
            case_details = get_case_details(case_number)
            if case_details:
                message = "Customer contact for SR "+str(case_number)+" is: <br>"
            else:
                message = "No case was found for SR " + str(case_number)
                case_details = False
        else:
            message = "No valid case number provided."
            case_details = False
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if case_details:
                message = "Customer contact for SR "+str(case_number)+" is: <br>"
            else:
                message = "No case was found for SR " + str(case_number)
                case_details = False
        else:
            message = "Sorry, no case number was found."
            case_details = False

    #Get the customer info from case details
    if case_details:
        case_customer_id = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_USER_ID']
        case_customer_first = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_USER_FIRST_NAME']
        case_customer_last = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_USER_LAST_NAME']
        if case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_EMAIL_IDS']:
            case_customer_email = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_EMAIL_IDS']['ID']
        else:
            case_customer_email = False
        if case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_BUSINESS_PHONE_NUMBERS']:
            case_customer_business = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_BUSINESS_PHONE_NUMBERS']['ID']
        else:
            case_customer_business = False
        if case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_MOBILE_PHONE_NUMBERS']:
            case_customer_mobile = case_details['RESPONSE']['CASES']['CASE_DETAIL']['CONTACT_MOBILE_PHONE_NUMBERS']['ID']
        else:
            case_customer_mobile = False
        message = message+case_customer_first+" "+case_customer_last
        message = message+"<br>CCO ID: "+case_customer_id if case_customer_id else message
        message = message+"<br>Email: "+case_customer_email if case_customer_email else message
        message = message+"<br>Business phone: "+case_customer_business if case_customer_business else message
        message = message+"<br>Mobile phone: "+case_customer_mobile if case_customer_mobile else message
    return message


# Returns case status and severity for provided case number
def send_status(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/title", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR "+str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR "+str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    # Get the title from the case details
    case_status = case_details['RESPONSE']['CASES']['CASE_DETAIL']['STATUS']
    case_severity = case_details['RESPONSE']['CASES']['CASE_DETAIL']['SEVERITY']
    message = "Status for SR {} is {} and Severity is {}".format(case_number, case_status, case_severity)
    return message


# Returns the RMA numbers if any are associated with the case
def send_rma_numbers(post_data):
    # Determine the Spark Room to send reply to
    room_id = post_data["data"]["roomId"]

    # Get the details about the message that was sent.
    message_id = post_data["data"]["id"]
    message_in = spark.messages.get(message_id)
    content = extract_message("/rma", message_in.text)

    # Check if case number is found in message content
    case_number = get_case_number(content)
    if case_number:
        case_details = get_case_details(case_number)
        if not case_details:
            message = "No case was found for SR " + str(case_number)
            return message
    else:
        room_name = get_room_name(room_id)
        case_number = get_case_number(room_name)
        if case_number:
            case_details = get_case_details(case_number)
            if not case_details:
                message = "No case was found for SR " + str(case_number)
                return message
        else:
            message = "Sorry, no case number was found."
            return message

    # Get the contract from the case details
    if case_details['RESPONSE']['CASES']['CASE_DETAIL']['RMAS']:
        case_rmas = case_details['RESPONSE']['CASES']['CASE_DETAIL']['RMAS']['ID']
        if type(case_rmas) is list:
            message = "The RMAs for SR {} are: {}".format(case_number, case_rmas)
        else:
            message = "The RMA for SR {} is: {}".format(case_number, case_rmas)
    else:
        message = "There are no RMAs for SR {}".format(case_number)

    return message


# Sample command function that just echos back the sent message
def send_echo(incoming):
    # Get sent message
    message = extract_message("/echo", incoming.text)
    return message


# Construct a help message for users.
def send_help(post_data):
    message = "Hello!  "
    message = message + "I understand the following commands:  \n"
    for c in commands.items():
        message = message + "* **%s**: %s \n" % (c[0], c[1])
    return message

# Test command function that prints a test string
def send_test():
    message = "This is a test message."
    return message


#
# Supporting functions
#

# Return contents following a given command
def extract_message(command, text):
    cmd_loc = text.find(command)
    message = text[cmd_loc + len(command):]
    return message

# Get access-token for Case API
def get_access_token():
    client_id = os.environ.get("CASE_API_CLIENT_ID")
    client_secret = os.environ.get("CASE_API_CLIENT_SECRET")
    grant_type = "client_credentials"
    url = "https://cloudsso.cisco.com/as/token.oauth2"
    payload = "client_id="+client_id+"&grant_type=client_credentials&client_secret="+client_secret
    headers = {
        'accept': "application/json",
        'content-type': "application/x-www-form-urlencoded",
        'cache-control': "no-cache"
    }
    response = requests.request("POST", url, data=payload, headers=headers)
    if (response.status_code == 200):
        return response.json()['access_token']
    else:
        response.raise_for_status()

# Get case details from CASE API
def get_case_details(case_number):
    access_token = get_access_token()

    url = "https://api.cisco.com/case/v1.0/cases/details/case_ids/" + str(case_number)
    headers = {
        'authorization': "Bearer " + access_token,
        'cache-control': "no-cache"
    }
    response = requests.request("GET", url, headers=headers)

    if (response.status_code == 200):
        # Uncomment to debug
        # sys.stderr.write(response.text)

        # Check if case was found
        if response.json()['RESPONSE']['COUNT'] == 1:
            return response.json()
        else:
            return False
    else:
        response.raise_for_status()


# Get all rooms name matching case number
def get_rooms(case_number):
    url = "https://api.ciscospark.com/v1/rooms/"

    headers = {
        'content-type': "application/json",
        'authorization': "Bearer "+globals()['spark_token'],
        'cache-control': "no-cache"
        }

    response = requests.request("GET", url, headers=headers)

    if (response.status_code == 200):
        test = [x for x in response.json()['items'] if str(case_number) in x['title']]
        return test
    else:
        response.raise_for_status()


# Get Spark room name
def get_room_name(room_id):
    url = "https://api.ciscospark.com/v1/rooms/"+room_id

    headers = {
        'content-type': "application/json",
        'authorization': "Bearer "+globals()["spark_token"],
        'cache-control': "no-cache"
        }

    response = requests.request("GET", url, headers=headers)
    if (response.status_code == 200):
        if 'errors' not in response.json():
            return response.json()['title']
        else:
            return False
    else:
        response.raise_for_status()


# Match case number in string
def get_case_number(content):
    # Check if there is a case number in the incoming message content
    pattern = re.compile("(6[0-9]{8})")
    match = pattern.search(content)

    if match:
        case_number = match.group(0)
        return case_number
    else:
        return False


# Create Spark Room
def create_room(case_number):
    case_title = get_case_title(case_number)
    if case_title:
        data = "{ \"title\": \"SR "+case_number+": "+case_title+"\" }"
    else:
        data = "{ \"title\": \"SR "+case_number+"\" }"
        
    url = "https://api.ciscospark.com/v1/rooms"

    headers = {
        'content-type': "application/json",
        'authorization': "Bearer "+globals()["spark_token"],
        'cache-control': "no-cache"
        }

    response = requests.request("POST", url, headers=headers, data=data)
    if (response.status_code == 200):
        return response.json()['id']
    else:
        response.raise_for_status()


# Get room membership
def get_membership(room_id):
    url = "https://api.ciscospark.com/v1/memberships?roomId="+room_id
    headers = {
        'content-type': "application/json",
        'authorization': "Bearer "+globals()["spark_token"],
        'cache-control': "no-cache"
        }

    response = requests.request("GET", url, headers=headers)
    if (response.status_code == 200):
        return response.json()
    else:
        response.raise_for_status()


# Get person_id for email address
def get_person_id(email):
    if check_email_syntax(email):
        url = "https://api.ciscospark.com/v1/people?email="+email
        headers = {
            'content-type': "application/json",
            'authorization': "Bearer "+globals()["spark_token"],
            'cache-control': "no-cache"
            }
    
        response = requests.request("GET", url, headers=headers)
        if (response.status_code == 200):
            if response.json()['items']:
                return response.json()['items'][0]['id']
            else:
                return False
        else:
            response.raise_for_status()
    else:
        return False


# Check if email is syntactically correct
def check_email_syntax(content):
    pattern = re.compile("^([a-zA-Z0-9_\-\.]+)@([a-zA-Z0-9_\-\.]+)\.([a-zA-Z]{2,5})$")

    if pattern.match(content):
        return True
    else:
        return False


# Create membership
def create_membership(person_id, new_room_id):
    data = "{ \"roomId\": \""+new_room_id+"\", \"personId\": \""+person_id+"\" }"

    url = "https://api.ciscospark.com/v1/memberships"

    headers = {
        'content-type': "application/json",
        'authorization': "Bearer "+globals()["spark_token"],
        'cache-control': "no-cache"
        }

    response = requests.request("POST", url, headers=headers, data=data)
    if (response.status_code == 200):
        return response.json()['id']
    else:
        response.raise_for_status()


# Check if room already exists for case and  user
def room_exists_for_user(case_number, email):
    person_id = get_person_id(email)
    rooms = get_rooms(case_number)
    for r in rooms:
        room_memberships = get_membership(r['id'])
        for m in room_memberships['items']:
            if m['personId'] == person_id:
                return r['id']
            else:
                continue


# Setup the Spark connection and WebHook
def spark_setup(email, token):
    # Update the global variables for config details
    globals()["spark_token"] = token
    globals()["bot_email"] = email

    sys.stderr.write("Spark Bot Email: " + bot_email + "\n")
    sys.stderr.write("Spark Token: REDACTED\n")

    # Setup the Spark Connection
    globals()["spark"] = CiscoSparkAPI(access_token=globals()["spark_token"])
    globals()["webhook"] = setup_webhook(globals()["bot_app_name"], globals()["bot_url"])
    sys.stderr.write("Configuring Webhook. \n")
    sys.stderr.write("Webhook ID: " + globals()["webhook"].id + "\n")


if __name__ == '__main__':
    # Entry point for bot
    # Retrieve needed details from environment for the bot
    bot_email = os.getenv("SPARK_BOT_EMAIL")
    spark_token = os.getenv("SPARK_BOT_TOKEN")
    bot_url = os.getenv("SPARK_BOT_URL")
    bot_app_name = os.getenv("SPARK_BOT_APP_NAME")

    # bot_url and bot_app_name must come in from Environment Variables
    if bot_url is None or bot_app_name is None:
            sys.exit("Missing required argument.  Must set 'SPARK_BOT_URL' and 'SPARK_BOT_APP_NAME' in ENV.")

    # Write the details out to the console
    sys.stderr.write("Spark Bot URL (for webhook): " + bot_url + "\n")
    sys.stderr.write("Spark Bot App Name: " + bot_app_name + "\n")

    # Placeholder variables for spark connection objects
    spark = None
    webhook = None

    # Check if the token and email were set in ENV
    if spark_token is None or bot_email is None:
        sys.stderr.write("Spark Config is missing, please provide via API.  Bot not ready.\n")
    else:
        spark_setup(bot_email, spark_token)
        spark = CiscoSparkAPI(access_token=spark_token)

    app.run(debug=True, host='0.0.0.0', port=int("5000"))
