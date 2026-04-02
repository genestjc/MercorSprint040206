import Mux from "@mux/mux-node";

export const muxConfigured =
  !!process.env.MUX_TOKEN_ID && !!process.env.MUX_TOKEN_SECRET;

export const mux = muxConfigured
  ? new Mux({
      tokenId: process.env.MUX_TOKEN_ID,
      tokenSecret: process.env.MUX_TOKEN_SECRET,
    })
  : null;
