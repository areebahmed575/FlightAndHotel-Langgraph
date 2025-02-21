from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
import uvicorn
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from agent import graph  
# Import the compiled LangGraph agent
from agent import graph, update_email_config

# Define a request model; here the client provides the initial message.
class TravelRequest(BaseModel):
    initial_message: str

class EmailRequest(BaseModel):
    email_to: str
    subject: str


app = FastAPI(
    title="Travel Agency API",
    description="API for generating domestic travel options within Pakistan using LangGraph."
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your frontend URL
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


## using asynchronous stream.
# @app.post("/plan_trip")
# async def plan_trip(request: TravelRequest):
#     try:
#         initial_state = {"messages": [HumanMessage(content=request.initial_message)]}
#         config = {"configurable": {"thread_id": "1"}}
        
       
#         response_chunks = [chunk async for chunk in graph.astream(initial_state, config)]
#         print("Response chunks:", response_chunks)
        
       
#         valid_chunks = [chunk for chunk in response_chunks if "__interrupt__" not in chunk]
#         if not valid_chunks:
#             raise HTTPException(status_code=500, detail="No valid AI response received.")
        
       
#         final_chunk = valid_chunks[-1]
        
       
#         ai_messages = final_chunk.get("assistant", {}).get("messages", [])
#         if not ai_messages:
#             raise HTTPException(status_code=500, detail="No AI message found in the final response.")
        
       
#         latest_ai_message = ai_messages[-1].content
#         return {"message": latest_ai_message}

        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error generating travel plan: {str(e)}")

@app.post("/plan_trip")
def plan_trip(request: TravelRequest):
    try:
        initial_state = {"messages": [HumanMessage(content=request.initial_message)]}
        config = {"configurable": {"thread_id": "1"}}
        result = graph.invoke(initial_state, config=config)
        return result['messages'][-1].content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating travel plan: {str(e)}")

@app.post("/send_email")
def send_email(request: EmailRequest):
    try:
        update_email_config(request.email_to, request.subject)
        config = {"configurable": {"thread_id": "1"}}
        result = graph.invoke(None, config=config)
        return {"status": "success", "message": "Email sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending email: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
