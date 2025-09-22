# from ws_client import WSClientSocket
# from ws_server import WSServer
import random
import threading
import websocket
import time
import asyncio
import websockets

# # port = random.randint(11000, 12000)
# # ws_client = WSClientSocket("0.0.0.0", 8765)
# # ws_client.start()

# # port = random.randint(11000, 12000)
# # print(port)
# # ws_server = WSServer("localhost", port)
# # ws_server.run()

# def start(host: str, port: str):
#     def run():
#         def on_message(self, ws, message):
#             print(f"Received message: {message}")

#         def on_error(self, ws, error):
#             print(f"Encountered error: {error}")

#         def on_close(self, ws, close_status_code, close_msg):
#             print("Connection closed")

#         def on_open(self, ws):
#             print("Connection opened")
#             ws.send("Hello, Server!")

#         ws = websocket.WebSocketApp(f"ws://{host}:{port}",
#                                     on_message=on_message,
#                                     on_error=on_error,
#                                     on_close=on_close)
#         ws.on_open = on_open
#         print(f"Socket running on: ws://{host}:{port}")
#         ws.run_forever()
#     print("Starting thread!!!!!!!!!!")
#     t1 = threading.Thread(target=run, daemon=True)
#     t1.start()

# if __name__=="__main__":
#     start("localhost", str(random.randint(11000, 12000)))

def on_message(wsapp, message):
    print(message)

def on_open(ws): 
    print("WS opened.....")

def on_reconnect(ws): 
    print("Reconnected......")

def on_error(ws, error): 
    print("Error in ws......", error)

def on_close(ws, status, message):
    print("WS CLosed!!!!!!")

async def start(host:str, port:str):
    wsapp = websocket.WebSocketApp(url=f"ws://{host}:{port}", on_message=on_message, on_open=on_open, 
                                    on_close=on_close, on_error=on_error, on_reconnect=on_reconnect)
    wsapp.run_forever()
    print(f"Server running on: ws://{host}:{port}")


def main():
    port = random.randint(11000, 12000)
    print(port)
    host = "127.0.0.1"
    asyncio.run(start(host, str(port)))
    
    

if __name__ == "__main__":
    main()