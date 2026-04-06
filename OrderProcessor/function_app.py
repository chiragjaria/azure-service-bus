import azure.functions as func
import json
import psycopg2
import os
import logging
from datetime import datetime

# Initialize logger
logger = logging.getLogger(__name__)

app = func.FunctionApp()

@app.function_name("OrderProcessor")
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="orders-queue",
    connection="SB_CONNECTION_STRING"
)
def order_processor(msg: func.ServiceBusMessage):
    """
    Service Bus Queue Trigger Function

    Purpose: Read order message from queue → Validate → Save to PostgreSQL

    Triggered Automatically When:
    - New message arrives in "orders-queue"

    Process:
    1. Parse message JSON
    2. Validate order data
    3. Connect to PostgreSQL
    4. Insert order into database
    5. Auto-delete message from queue (on success)

    If Error Occurs:
    - Message stays in queue
    - Retried up to 10 times (configured in Terraform)
    - After 10 failures → moved to dead-letter queue
    """

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

        # Validate items is not empty
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
        # STEP 4: Connect to PostgreSQL database
        # ══════════════════════════════════════════════════════════
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_pass,
            connect_timeout=10          # ✅ Added: avoid hanging indefinitely
        )

        cursor = conn.cursor()
        logger.info("✅ Connected to PostgreSQL")

        # ══════════════════════════════════════════════════════════
        # STEP 5: Create table if it doesn't exist (safe bootstrap)
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
                json.dumps(order_data["items"]),    # Store items as JSON
                order_data.get("total_amount", 0),
                "completed",                         # Mark as completed
                order_data["created_at"],
                datetime.utcnow().isoformat()
            )
        )

        conn.commit()
        logger.info(f"✅ Order {order_data['order_id']} saved to database")

        # ══════════════════════════════════════════════════════════
        # STEP 7: Message auto-deletes from queue on success
        # ══════════════════════════════════════════════════════════
        logger.info(f"✅ Order {order_data['order_id']} processed completely!")
        logger.info("🗑️  Message automatically deleted from queue")

    except psycopg2.Error as db_error:
        logger.error(f"❌ Database error: {str(db_error)}")
        if conn:
            conn.rollback()             # ✅ Added: rollback on DB error
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
        # ✅ Added: always close DB resources cleanly
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            logger.info("🔒 Database connection closed")
