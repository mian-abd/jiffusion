---

J - Jev

Jiff - gif

usion - diffusion

---

What if we just like, followed how temperature/schedulers work?

And then ask jev to pick the “Best one” for that image prompt

We have 5 different light levels of “intensity”.

“space”, **`░` ▒  ▓ █**

Sample schedule:

1. Complete random noise
2. Flip 80% of squares within any range of intensity
3. Flip 70% of squares within any range of intensity
4. Flip 60% of squares under 3 levels of intensity
5. Flip 50% of squares under 2 levels of intensity
6. Flip 40% of squares under 2 levels of intensity
7. Flip 40% of squares under 1 level of intensity
8. Flip 40% of squares under 1 level of intensity
9. Flip 20% of squares under 1 level of intensity
10. Flip 10% of squares under 1 level of intensity
11. Flip 10% of squares under 1 level of intensity
12. Flip 10% of squares under 1 level of intensity

Within each step, we give like 1000 choices to jev for each “step”.

The exact numbers here can be fine tuned.

Maybe add simulated annealing or like some sort of cosine thing to vary it more. Whatever ya feel.

We can “encode videos” as a series of code blocks.
