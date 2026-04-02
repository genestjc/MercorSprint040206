import Stripe from "stripe";

export const stripeConfigured =
  !!process.env.STRIPE_SECRET_KEY && !!process.env.STRIPE_PRICE_ID;

export const stripe = stripeConfigured
  ? new Stripe(process.env.STRIPE_SECRET_KEY as string, {
      apiVersion: "2024-06-20",
    })
  : null;

export const STRIPE_PRICE_ID = process.env.STRIPE_PRICE_ID;
