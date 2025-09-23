# batch_handler.py
import logging

def execute_requests_in_batches(drive_service, requests, progress_callback=None):
    """
    Executes a list of Google Drive API requests in batches of 100.

    Args:
        drive_service: The authenticated Google Drive service object.
        requests: A list of API request objects to be executed.
        progress_callback: An optional function to report progress.

    Returns:
        A list of all the results from the API calls.
    """
    batch_size = 100  # Google Drive API's maximum batch size
    all_results = []
    total_requests = len(requests)

    for i in range(0, total_requests, batch_size):
        batch_requests = requests[i:i + batch_size]
        
        if progress_callback:
            # Update progress based on the start of the current batch
            progress_callback(i, total_requests)

        batch = drive_service.new_batch_http_request()
        
        # Store requests to process their responses later
        request_map = {}

        def create_callback(request_id):
            def callback(resp_request_id, response, exception):
                if exception:
                    logging.error(f"Batch request {resp_request_id} failed: {exception}")
                    request_map[resp_request_id]['response'] = None
                else:
                    request_map[resp_request_id]['response'] = response
            return callback

        for req in batch_requests:
            request_id = str(len(request_map))
            request_map[request_id] = {'request': req, 'response': None}
            batch.add(req, callback=create_callback(request_id), request_id=request_id)
        
        try:
            batch.execute()
            # Extract responses in the original order
            for request_id in sorted(request_map.keys(), key=int):
                all_results.append(request_map[request_id]['response'])
        except Exception as e:
            logging.error(f"A critical error occurred during batch execution: {e}")
            # Add None for all requests in the failed batch
            all_results.extend([None] * len(batch_requests))

    if progress_callback:
        progress_callback(total_requests, total_requests) # Signal completion

    return all_results
