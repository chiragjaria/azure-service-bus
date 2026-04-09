import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import json
import os
import logging
import psycopg2
from datetime import datetime

# Initialize logger
logger = logging.getLogger(__name__)

app = func.FunctionApp()


# ══════════════════════════════════════════════════════════════════════
# FUNCTION 1: OrderSender — HTTP Trigger
# Purpose: Receive order from client → Send to Service Bus queue
#
# Expected Input (JSON):
# {
#     "order_id": 1,
#     "customer_name": "John Doe",
#     "items": ["pizza", "coke"],
#     "total_amount": 500
# }
# ══════════════════════════════════════════════════════════════════════

@app.function_name("OrderSender")
@app.route(route="orders", methods=["POST"],auth_level=func.AuthLevel.ANONYMOUS)
def order_sender(req: func.HttpRequest) -> func.HttpResponse:

    try:
        # ══════════════════════════════════════════════════════════
        # STEP 1: Get order data from HTTP request
        # ══════════════════════════════════════════════════════════
        order_data = req.get_json()

        # Validate required fields
        required_fields = ["order_id", "customer_name", "items"]
        for field in required_fields:
            if field not in order_data:
                return func.HttpResponse(
                    json.dumps({"error": f"Missing field: {field}"}),
                    status_code=400,
                    mimetype="application/json"
                )

        logger.info(f"📥 Received order: {order_data['order_id']} from {order_data['customer_name']}")

        # ══════════════════════════════════════════════════════════
        # STEP 2: Get Service Bus credentials from environment
        # ══════════════════════════════════════════════════════════
        sb_connection_string = os.getenv("SB_CONNECTION_STRING")
        queue_name = os.getenv("SB_QUEUE_NAME")

        if not sb_connection_string or not queue_name:
            logger.error("❌ Service Bus credentials missing!")
            return func.HttpResponse(
                json.dumps({"error": "Service Bus not configured"}),
                status_code=500,
                mimetype="application/json"
            )

        # ══════════════════════════════════════════════════════════
        # STEP 3: Connect to Service Bus and send message
        # ══════════════════════════════════════════════════════════
        message_body = {
            "order_id": order_data["order_id"],
            "customer_name": order_data["customer_name"],
            "items": order_data["items"],
            "total_amount": order_data.get("total_amount", 0),
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending"
        }

        with ServiceBusClient.from_connection_string(sb_connection_string) as client:
            with client.get_queue_sender(queue_name) as sender:
                sender.send_messages(ServiceBusMessage(json.dumps(message_body)))

        logger.info(f"✅ Order {order_data['order_id']} sent to queue")

        # ══════════════════════════════════════════════════════════
        # STEP 4: Return success response
        # ══════════════════════════════════════════════════════════
        response = {
            "status": "Order received",
            "order_id": order_data["order_id"],
            "message": "Order queued for processing",
            "queue_name": queue_name
        }

        return func.HttpResponse(
            json.dumps(response),
            status_code=200,
            mimetype="application/json"
        )

    except ValueError:
        logger.error("❌ Invalid JSON in request")
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


# ══════════════════════════════════════════════════════════════════════
# FUNCTION 2: OrderProcessor — Service Bus Queue Trigger
# Purpose: Read order message from queue → Validate → Save to PostgreSQL
#
# Triggered automatically when a new message arrives in "orders-queue"
# ══════════════════════════════════════════════════════════════════════

@app.function_name("OrderProcessor")
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="orders-queue",
    connection="SB_CONNECTION_STRING"
)
def order_processor(msg: func.ServiceBusMessage):

    conn = None
    cursor = None

    try:
        # ══════════════════════════════════════════════════════════
        # STEP 1: Parse message from Service Bus queue
        # ══════════════════════════════════════════════════════════
        message_body = msg.get_body().decode('utf-8')
        order_data = json.loads(message_body)

        logger.info(f"📨 Processing order: {order_data['order_id']}")

        # ══════════════════════════════════════════════════════════
        # STEP 2: Validate order data
        # ══════════════════════════════════════════════════════════
        required_fields = ["order_id", "customer_name", "items", "created_at"]
        for field in required_fields:
            if field not in order_data:
                logger.error(f"❌ Missing field: {field}")
                raise ValueError(f"Missing required field: {field}")

        if not order_data["items"] or len(order_data["items"]) == 0:
            logger.error("❌ Order has no items")
            raise ValueError("Order must contain at least one item")

        logger.info(f"✅ Order validated: {len(order_data['items'])} items")

        # ══════════════════════════════════════════════════════════
        # STEP 3: Get database credentials from environment
        # ══════════════════════════════════════════════════════════
        db_host = os.getenv("DB_HOST")
        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER")
        db_pass = os.getenv("DB_PASS")

        if not all([db_host, db_name, db_user, db_pass]):
            logger.error("❌ Database credentials missing!")
            raise Exception("Database configuration incomplete")

        # ══════════════════════════════════════════════════════════
        # STEP 4: Connect to PostgreSQL
        # ══════════════════════════════════════════════════════════
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_pass,
            connect_timeout=10
        )
        cursor = conn.cursor()
        logger.info("✅ Connected to PostgreSQL")

        # ══════════════════════════════════════════════════════════
        # STEP 5: Create table if it doesn't exist
        # ══════════════════════════════════════════════════════════
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id            SERIAL PRIMARY KEY,
                order_id      INTEGER NOT NULL,
                customer_name VARCHAR(255) NOT NULL,
                items         JSONB NOT NULL,
                total_amount  NUMERIC(10, 2) DEFAULT 0,
                status        VARCHAR(50) DEFAULT 'pending',
                created_at    TIMESTAMP,
                processed_at  TIMESTAMP
            )
        """)
        conn.commit()

        # ══════════════════════════════════════════════════════════
        # STEP 6: Insert order into database
        # ══════════════════════════════════════════════════════════
        insert_query = """
            INSERT INTO orders (
                order_id,
                customer_name,
                items,
                total_amount,
                status,
                created_at,
                processed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        cursor.execute(
            insert_query,
            (
                order_data["order_id"],
                order_data["customer_name"],
                json.dumps(order_data["items"]),
                order_data.get("total_amount", 0),
                "completed",
                order_data["created_at"],
                datetime.utcnow().isoformat()
            )
        )

        conn.commit()
        logger.info(f"✅ Order {order_data['order_id']} saved to database")
        logger.info(f"✅ Order {order_data['order_id']} processed completely!")
        logger.info("🗑️  Message automatically deleted from queue")

    except psycopg2.Error as db_error:
        logger.error(f"❌ Database error: {str(db_error)}")
        if conn:
            conn.rollback()
        raise Exception(f"Database error: {str(db_error)}")

    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in message")
        raise Exception("Message is not valid JSON")

    except ValueError as val_error:
        logger.error(f"❌ Validation error: {str(val_error)}")
        raise Exception(f"Validation failed: {str(val_error)}")

    except Exception as error:
        logger.error(f"❌ Unexpected error: {str(error)}")
        raise Exception(f"Processing failed: {str(error)}")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logger.info("🔒 Database connection closed")
