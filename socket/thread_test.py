import datetime
import threading
import time
import traceback
def run():
    print("Running run,.......")
    count = 0
    try:
        with open("file.txt", "w") as op_file:
            while count <= 10:
                op_file.write(str(datetime.datetime.now()))
                op_file.write("\n")
                count += 1
                time.sleep(1)
    except Exception as e:
        traceback.print_exc()
        traceback.print_stack()

def main():
    t1 = threading.Thread(target=run, daemon=True)
    t1.start()
    time.sleep(15)

if __name__ == "__main__":
    main()