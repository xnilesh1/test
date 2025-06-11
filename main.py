import streamlit as st
import dotenv
import os
import json
from datetime import datetime
import google.generativeai as genai
from google.generativeai import types
from google.generativeai import protos
from tools import (
        query_acts_schema,
        query_laws_schema,
    AVAILABLE_TOOLS,
)
from prompts import system_prompt

# Load environment variables
dotenv.load_dotenv()

# Page configuration

# Configure the Gemini client
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Set up function declarations
legal_tools = [
    types.Tool(function_declarations=[
    query_acts_schema,
    query_laws_schema,
    ])
]

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=system_prompt,
    tools=legal_tools,
)

def load_custom_css(file_path):
    with open(file_path) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

load_custom_css("custom.css")

# Initialize session state variables
if "messages" not in st.session_state:
    st.session_state.messages = []
if "feedback_given" not in st.session_state:
    st.session_state.feedback_given = {}
if "chat" not in st.session_state:
    # Start a new chat session and store it in the session state
    st.session_state.chat = model.start_chat(history=[])

# Current time for timestamp
st.session_state.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Function to save feedback to JSON files
def save_feedback(user_input, assistant_response, feedback_type):
    os.makedirs("feedback", exist_ok=True)
    json_file = f"feedback/{feedback_type}.json"
    feedback_data = {
        "user_input": user_input,
        "assistant_response": assistant_response,
        "timestamp": st.session_state.current_time
    }
    existing_data = []
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = []
    existing_data.append(feedback_data)
    with open(json_file, 'w') as f:
        json.dump(existing_data, f, indent=2)

# App title
st.title("✨ Caseone AI")

# Sidebar for settings
with st.sidebar:
    st.subheader("Controls")
    if st.button("Clear Chat", key="clear_chat"):
        st.session_state.messages = []
        st.session_state.feedback_given = {}
        # Reset the chat object
        st.session_state.chat = model.start_chat(history=[])
        st.rerun()

# Sample prompts
st.subheader("Try these!")
party_prompts = [
    "What is the Prevention of Corruption Act?",
    "Explain the main sections of the Companies Act 2013",
]
col1, col2 = st.columns(2)
with col1:
    if st.button(party_prompts[0], key="prompt1"): st.session_state.temp_input = party_prompts[0]
with col2:
    if st.button(party_prompts[1], key="prompt2"): st.session_state.temp_input = party_prompts[1]

# Display chat messages from history
for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            if "prompt_tokens" in message and "candidates_tokens" in message:
                st.caption(f"Input Tokens: {message['prompt_tokens']} | Output Tokens: {message['candidates_tokens']}")
            msg_id = f"msg_{idx // 2}"
            if msg_id not in st.session_state.feedback_given:
                # Use a unique key for each feedback component
                feedback = st.feedback("thumbs", key=f"feedback_{msg_id}")
                if feedback and isinstance(feedback, dict) and "score" in feedback:
                    feedback_type = "liked" if feedback["score"] == "👍" else "disliked"
                    save_feedback(st.session_state.messages[idx-1]["content"], message["content"], feedback_type)
                    st.session_state.feedback_given[msg_id] = feedback_type
                    st.rerun()
            elif msg_id in st.session_state.feedback_given:
                feedback_type = st.session_state.feedback_given[msg_id]
                st.caption(f"Thank you for your feedback! ({feedback_type})")


# User input handling
user_input = st.chat_input("Ask me anything ✨...")
if "temp_input" in st.session_state and st.session_state.temp_input:
    user_input = st.session_state.temp_input
    st.session_state.temp_input = None

if user_input:
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    # Get assistant response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            chat = st.session_state.chat
            response = chat.send_message(user_input)
            print(response)

            prompt_tokens = 0
            candidates_tokens = 0
            try:
                prompt_tokens = response.usage_metadata.prompt_token_count
                candidates_tokens = response.usage_metadata.candidates_token_count
            except (AttributeError, TypeError):
                pass

            # Extract function call from candidates if present
            if response.candidates and response.candidates[0].content.parts and any(p.function_call for p in response.candidates[0].content.parts):
                
                tool_responses = []
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        function_call = part.function_call
                        function_name = function_call.name
                        if function_name in AVAILABLE_TOOLS:
                            function_to_call = AVAILABLE_TOOLS[function_name]
                            function_args = dict(function_call.args)
                            function_response = function_to_call(**function_args)

                            tool_responses.append(protos.Part(
                                function_response=protos.FunctionResponse(
                                    name=function_name,
                                    response=function_response
                                )
                            ))

                if tool_responses:
                    response = chat.send_message(tool_responses)
                    try:
                        prompt_tokens += response.usage_metadata.prompt_token_count
                        candidates_tokens += response.usage_metadata.candidates_token_count
                    except (AttributeError, TypeError):
                        pass

            full_response = response.text
            st.markdown(full_response)

    # Clean up chat history to reduce token count
    # We only want to keep the user's message and the final assistant response
    if st.session_state.chat.history:
        new_history = []
        # The last two messages are the user's query and the model's final response.
        # Before that, there could be tool calls and responses that we want to discard
        # from the history that will be sent in the next turn.
        # We find the last user message that is not a tool response.
        
        # Copy all but the last two messages which are user input and model response for the current turn.
        # The history contains everything, including tool calls from previous turns that we have already filtered.
        # We need to preserve them.
        
        # A better approach is to filter out unwanted messages.
        
        temp_history = st.session_state.chat.history
        
        # We want to keep messages that are not function calls or function responses
        new_history = [
            msg for msg in temp_history
            if not any(part.function_call for part in msg.parts) and not any(part.function_response for part in msg.parts)
        ]
        
        st.session_state.chat.history = new_history

    st.session_state.messages.append({
        "role": "assistant",
        "content": full_response,
        "prompt_tokens": prompt_tokens,
        "candidates_tokens": candidates_tokens
    })
    st.rerun()

