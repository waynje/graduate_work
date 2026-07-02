from kafka import KafkaConsumer


consumer = KafkaConsumer(
    'messages',
    bootstrap_servers=['localhost:9094'],
    auto_offset_reset='earliest',
    group_id='echo-messages-to-stdout',
)

for message in consumer:
    print(message.value) 