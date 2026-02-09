from openai import AzureOpenAI

client = AzureOpenAI(
    api_key="1x9mGKh7CjP4V3jMntg5Lv28h2WLgUmNw0zQyutUvhTIBN4B6h0IJQQJ99CAACYeBjFXJ3w3AAABACOGajy2",
    api_version="2024-02-01", 
    azure_endpoint="https://thtn-ai-9.openai.azure.com/"
)

deployment_name = "gpt-4o-mini" 

try:
    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "user", "content": "Tell me about Prodapt!!"}
        ]
    )
    print(response.choices[0].message.content)

except Exception as e:
    print(f"Error: {e}")