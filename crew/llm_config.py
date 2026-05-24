import os
from dotenv import load_dotenv, find_dotenv
from crewai import LLM

# Force-load the .env file specifically from the current directory
load_dotenv(find_dotenv())

class LLMConfig:
    # Debug: Print what the system sees
    provider = os.getenv("LLM_PROVIDER")
    print(f"[DEBUG] LLM_PROVIDER detected as: {provider}")
    print(f"[DEBUG] Current Working Directory: {os.getcwd()}")

    @classmethod
    def get_llm(cls, role="general"):
        # Default to local if provider is None
        current_provider = os.getenv("LLM_PROVIDER", "local")
        
        if current_provider == "groq":
            print(f"[DEBUG] Initializing Groq with model: {os.getenv('GROQ_MODEL')}")
            return LLM(
                model=f"groq/{os.getenv('GROQ_MODEL')}",
                temperature=0, # Low temperature is CRITICAL for preventing hallucinated tool syntax
                api_key=os.getenv("GROQ_API_KEY"),
                # CRITICAL: This forces CrewAI to use text prompts for tools instead of breaking Groq endpoints
                native_tool_calling=False 
            )
        
        elif current_provider == "gemini":
            print(f"[DEBUG] Initializing Gemini...")
            return LLM(
                model=f"gemini/{os.getenv('GEMINI_MODEL')}",
                api_key=os.getenv("GEMINI_API_KEY")
            )
            
        else:
            print(f"[DEBUG] Falling back to Local Ollama...")
            # model_name = "deepseek-r1" if role == "analyst" else "llama3.2"
            # return LLM(
            #     model=f"ollama/{model_name}",
            #     base_url="http://localhost:11434"
            # )
            return None
