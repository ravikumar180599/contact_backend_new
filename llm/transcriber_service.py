import random

char_set = "abcdefghijklmnopqrstuvwxyz"

class TranscriberService:
    @staticmethod
    def transcribe(audio_str: str):
        print("initialized transcriber service instance!!!!")
        response = ""
        for _ in range(20):
            word_len = random.randint(3, 10)
            word = ""
            for _ in range(word_len):
                word += char_set[random.randint(0, 25)]
            response += word
        return response
