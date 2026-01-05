## Q&A, Shortcut, and Debugger Alignment Notes

Context captured from product conversation (Nov 10 2025):

> If a client confirms multiple required gates (e.g., shares date + capacity + room) in one turn, treat it as a shortcut: acknowledge every confirmed field in the reply, set the corresponding gate flags, and still respect any pending HIL reviews (shortcuts never skip HIL).  
>  
> When a client confirms an entire step and immediately asks a general question, answer the Q&A first (mark the subloop in the debugger), then resume the default flow exactly where it left off.  
>  
> The debugger must highlight when we run a general Q&A branch or a shortcut (color badges + legend on the right). It should never look like we “jumped” steps even if a shortcut runs; the trace needs to show Step 1 → Step 2 → Step 3 in sequence, and the shortcut summary should repeat the confirmed steps (“Date confirmed, Room confirmed, special request sent to manager”).  
>  
> For vague date requests (“sometime in February / Saturdays”), never trigger the room-availability shortcut immediately. Always run date confirmation first, capture the client’s explicit choice, and only then move to room ranking. The reply must surface all information the client asked for (available dates, per-room fit, menu/product matches).

Keep this document in sync whenever we update the shortcut or debugger rules so future work can revisit the exact requirements that motivated the changes.
