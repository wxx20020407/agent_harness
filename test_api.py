from openai import OpenAI 

api_key = "sk-6b64f5d737a04555a7ae8b12e4e8d064"

api_base = "http://aihub.x-ringtek1.com/m/v1"

client = OpenAI(
    api_key=api_key,
    base_url=api_base,
)

chat_response = client.chat.completions.create(
    model="MiMo-V2-Flash",
    messages=[
        {"role":"system", "content":"You are a helpful assistant."},
        {"role":"user", "content":"你好"},
    ]
)

print("chat response:", chat_response.choices)