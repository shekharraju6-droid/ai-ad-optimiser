import os
from google import genai

def run_verification():
    # Double-checking that your terminal actually sees the key
    if not os.environ.get("GEMINI_API_KEY"):
        print("❌ Error: GEMINI_API_KEY environment variable not found.")
        print("Please rerun Step 3 to set your key.")
        return

    print("Connecting to Gemini...")
    
    # Initialize the client (it automatically picks up the environment variable)
    client = genai.Client()

    # Make a quick test request
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Confirm connection by replying with: "System online, Laksh!"',
    )

    print("\n--- Response from AI ---")
    print(response.text)
    print("------------------------")

if __name__ == "__main__":
    run_verification()
