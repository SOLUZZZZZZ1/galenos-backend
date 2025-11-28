session = stripe.checkout.Session.create(
    mode="subscription",
    payment_method_types=["card"],
    line_items=[
        {
            "price": STRIPE_PRICE_ID,
            "quantity": 1,
        }
    ],
    subscription_data={
        "trial_period
