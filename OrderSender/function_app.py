import azure.functions as func
from azure.servicebus import ServiceBusClient
import json
import os
import logging
from datetime import datetime

# Initialize logger
logger = logging.getLogger(__name__)

app = func.FunctionApp()

@app.function_name("OrderSender")
@app.route(route="orders", methods=["POST"])
def order_sender(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP Trigger Function
    
    Purpose: Receive order from client → Send to Service Bus queue
    
    Expected Input (JSON):
    {
        "order_id": 1,
        "customer_name": "John Doe",
        "items": ["pizza", "coke"],
        "total_amount": 500
    }
    
    Response:
    {
        "status": "Order received",
        "order_id": 1,
        "message": "Order queued for processing"
    }
    """
    
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
        with ServiceBusClient.from_connection_string(sb_connection_string) as client:
            sender = client.get_queue_sender(queue_name)
            
            # Create message payload
            message_body = {
                "order_id": order_data["order_id"],
                "customer_name": order_data["customer_name"],
                "items": order_data["items"],
                "total_amount": order_data.get("total_amount", 0),
                "created_at": datetime.utcnow().isoformat(),
                "status": "pending"
            }
            
            # Send message to queue
            sender.send_message(json.dumps(message_body))
        
        logger.info(f"✅ Order {order_data['order_id']} sent to queue")
        
        # ══════════════════════════════════════════════════════════
        # STEP 4: Return success response to client immediately
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
