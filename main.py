from fastapi import FastAPI, Request

app=FastAPI(title="Performa AI")

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)