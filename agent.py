import datetime
import os
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
import serpapi
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv, find_dotenv
from dataclasses import dataclass
# Load API keys from environment variables

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
open_api_key = os.getenv("OPENAI_API_KEY")
print(f"SERPAPI_API_KEY",SERPAPI_API_KEY)



llm = ChatOpenAI(model="gpt-4o-mini", api_key=open_api_key)



CURRENT_YEAR = datetime.datetime.now().year

# Prompts for the agent and the email conversion
TOOLS_SYSTEM_PROMPT = f"""You are a smart travel agency specializing in Pakistan tourism.
You provide travel options only for domestic travel within Pakistan.
Use the tools to look up information on hotels and flights available in Pakistan.
If a user requests travel outside Pakistan, politely inform them that you only support domestic options.
YOUR RESPONSE MUST ALWAYS BE IN VALID JSON FORMAT following this structure, with EXACTLY 3 flights and 3 hotels:
{{
    "flights": [
        {{
            "airline": "Airline Name",
            "booking_link": "URL to booking page"
            "departure_airport": "Airport code",
            "arrival_airport": "Airport code",
            "departure_time": "Time in HH:MM format",
            "arrival_time": "Time in HH:MM format",
            "duration": "Duration in hours and minutes",
            "price": float,
            "currency": "PKR",
            "airline_logo": "URL to airline logo",
           
        }},
        // EXACTLY 2 MORE FLIGHT OPTIONS
    ],
    "hotels": [
        {{
            "name": "Hotel Name",
            "booking_link": "URL to booking page"
            "description": "Brief description",
            "location": "Address",
            "price_per_night": float,
            "total_price": float,
            "currency": "PKR",
            "rating": float,
            "reviews_count": integer,
            "amenities": ["amenity1", "amenity2"],
            "hotel_logo": "URL to hotel image",
        }},
        // EXACTLY 2 MORE HOTEL OPTIONS
    ],
    "total_package_price": float,
    "currency": "PKR"
}}


The current year is {CURRENT_YEAR}.
If you need to look up some information before asking a follow up question, you are allowed to do that!
I want to have in your output links to hotels websites and flights websites (if possible).
I want to have as well the logo of the hotel and the logo of the airline company (if possible).
In your output always include the price of the flight and the price of the hotel and the currency as well (if possible).
For example, for hotels:
Rate: Rs 50000 per night
Total: Rs 30,488

"""

EMAILS_SYSTEM_PROMPT = """Your task is to convert structured markdown-like text into a valid HTML email body.

- Do not include a ```html preamble in your response.
- The output should be in proper HTML format, ready to be used as the body of an email.
Here is an example:
<example>
Input:

I want to travel to Islamabad from Karachi from October 1-7. Find me flights and 4-star hotels.

Expected Output:

<!DOCTYPE html>
<html>
<head>
    <title>Flight and Hotel Options</title>
</head>
<body>
    <h2>Flights from Islamabad to Karachi</h2>
    <ol>
        <li>
            <strong>Pakistan International Airlines</strong><br>
            <strong>Departure:</strong> Jinnah International Airport (KHI) at 10:25 AM<br>
            <strong>Arrival:</strong> Islamabad International Airport (ISB) at 12:25 PM<br>
            <strong>Duration:</strong> 1 hour 30 minutes<br>
            <strong>Aircraft:</strong> ATR 72<br>
            <strong>Class:</strong> Economy<br>
            <strong>Price:</strong> Rs 41,145<br>
            <a href="https://www.piac.com.pk">Visit Website</a>
            <img src="https://www.gstatic.com/flights/airline_logos/70px/ER.png" alt="PIA"><br>
           
        </li>
        <!-- More flight entries -->
    </ol>

    <h2>4-Star Hotels in Islamabad</h2>
    <ol>
        <li>
            <strong>Pearl Continental Hotel</strong><br>
            <strong>Description:</strong> Luxurious hotel offering comfortable rooms, fine dining, and modern amenities.<br>
            <strong>Location:</strong> Islamabad city center near key attractions and business districts.<br>
            <strong>Rate per Night:</strong> Rs 18,000<br>
            <strong>Total Rate:</strong> Rs 126,000<br>
            <strong>Rating:</strong> 4.5/5 (1,200 reviews)<br>
            <a href="https://www.pchotels.com/">Visit Website</a>
            <img src="https://lh5.googleusercontent.com/p/AF1QipNDUrPJwBhc9ysDhc8LA822H1ZzapAVa-WDJ2d6=s287-w287-h192-n-k-no-v1" alt="Pearl Continental Hotel"><br>
           
        </li>
        <!-- More hotel entries -->
    </ol>
</body>
</html>
</example>
"""

# Instantiate the LLM
llm = ChatOpenAI(model="gpt-4o-mini", api_key=open_api_key)
llm_with_tools = None  # We will bind the tools after they are defined

# Define the agent state (here we use a simple subclass of MessagesState)
class AgentState(MessagesState):
    pass



class FlightsInput(BaseModel):
    departure_airport: Optional[str] = Field(description='Departure airport code (IATA)')
    arrival_airport: Optional[str] = Field(description='Arrival airport code (IATA)')
    outbound_date: Optional[str] = Field(description='Parameter defines the outbound date. The format is YYYY-MM-DD. e.g. 2024-06-22')
    return_date: Optional[str] = Field(description='Parameter defines the return date. The format is YYYY-MM-DD. e.g. 2024-06-28')
    adults: Optional[int] = Field(1, description='Parameter defines the number of adults. Default to 1.')
    children: Optional[int] = Field(0, description='Parameter defines the number of children. Default to 0.')
    infants_in_seat: Optional[int] = Field(0, description='Parameter defines the number of infants in seat. Default to 0.')
    infants_on_lap: Optional[int] = Field(0, description='Parameter defines the number of infants on lap. Default to 0.')


class FlightsInputSchema(BaseModel):
    params: FlightsInput


@tool(args_schema=FlightsInputSchema)
def flights_finder(params: FlightsInput):
    '''
    Find flights using the Google Flights engine.

    Returns:
        dict: Flight search results.
    '''

    params = {
        'api_key': SERPAPI_API_KEY,
        'engine': 'google_flights',
        'hl': 'en',
        'gl': 'pk',
        'departure_id': params.departure_airport,
        'arrival_id': params.arrival_airport,
        'outbound_date': params.outbound_date,
        'return_date': params.return_date,
        'currency': 'PKR',
        'adults': params.adults,
        'infants_in_seat': params.infants_in_seat,
        'stops': '1',
        'infants_on_lap': params.infants_on_lap,
        'children': params.children
    }

    try:
        search = serpapi.search(params)
        results = search.data['best_flights']
    except Exception as e:
        results = str(e)
    return results



class HotelsInput(BaseModel):
    q: str = Field(description='Location of the hotel')
    check_in_date: str = Field(description='Check-in date. The format is YYYY-MM-DD. e.g. 2024-06-22')
    check_out_date: str = Field(description='Check-out date. The format is YYYY-MM-DD. e.g. 2024-06-28')
    sort_by: Optional[str] = Field(8, description='Parameter is used for sorting the results. Default is sort by highest rating')
    adults: Optional[int] = Field(1, description='Number of adults. Default to 1.')
    children: Optional[int] = Field(0, description='Number of children. Default to 0.')
    rooms: Optional[int] = Field(1, description='Number of rooms. Default to 1.')
    hotel_class: Optional[str] = Field(
        None, description='Parameter defines to include only certain hotel class in the results. for example- 2,3,4')


class HotelsInputSchema(BaseModel):
    params: HotelsInput


@tool(args_schema=HotelsInputSchema)
def hotels_finder(params: HotelsInput):
    '''
    Find hotels using the Google Hotels engine.

    Returns:
        dict: Hotel search results.
    '''
    print(f"calling...")



    params = {
        'api_key': SERPAPI_API_KEY,
        'engine': 'google_hotels',
        'hl': 'en',
        'gl': 'pk',
        'q': params.q,
        'check_in_date': params.check_in_date,
        'check_out_date': params.check_out_date,
        'currency': 'PKR',
        'adults': params.adults,
        'children': params.children,
        'rooms': params.rooms,
        'sort_by': params.sort_by,
        'hotel_class': params.hotel_class
    }
    print(f"calling again...")

    search = serpapi.search(params)
    results = search.data
    print(f"hotels results",results)
    return results['properties'][:5]




# Bind our tools to the LLM
tools = [flights_finder, hotels_finder]
llm_with_tools = llm.bind_tools(tools)

############################
# Graph Node Functions
############################

def assistant(state: AgentState):
    # Prepend the system prompt to the conversation
    messages = state['messages']
    messages = [SystemMessage(content=TOOLS_SYSTEM_PROMPT)] + messages
    message = llm_with_tools.invoke(messages)
    return {'messages': [message]}

def exists_action(state: AgentState):
    # Check if the latest assistant message contained any tool calls
    result = state['messages'][-1]
    if len(result.tool_calls) == 0:
        return 'email_sender'
    return 'more_tools'

@dataclass
class EmailConfig:
    email_to: Optional[str] = None
    subject: Optional[str] = None

# Create a global email config instance
email_config = EmailConfig()

def update_email_config(email_to: str, subject: str):
    """Update the email configuration"""
    global email_config
    email_config.email_to = email_to
    email_config.subject = subject

# Modify the email_sender function
def email_sender(state: AgentState):
    print('Sending email')
    email_message = [
        SystemMessage(content=EMAILS_SYSTEM_PROMPT),
        HumanMessage(content=state['messages'][-1].content)
    ]
    email_response = llm.invoke(email_message)
    print('Email content:', email_response.content)
    
    # Use the dynamic email configuration
    print(f"email_config.email_to",email_config.email_to)
    print(f"email_config.subject",email_config.subject)
    message = Mail(
        from_email="areeb.ahmed.langgraph@gmail.com",
        to_emails=email_config.email_to,  # Use dynamic email
        subject=email_config.subject,      # Use dynamic subject
        html_content=email_response.content
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print("SendGrid response:", response)
    except Exception as e:
        print("SendGrid error:", str(e))
    return state

############################
# Build the Graph
############################

builder: StateGraph = StateGraph(AgentState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_node("email_sender", email_sender)

# Define control flow edges
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", exists_action, {"more_tools": "tools", "email_sender": "email_sender"})
builder.add_edge("tools", "assistant")
builder.add_edge("email_sender", END)

memory = MemorySaver()
graph: CompiledStateGraph = builder.compile(interrupt_before=["email_sender"], checkpointer=memory)

# The graph object is now available for import in main.py
