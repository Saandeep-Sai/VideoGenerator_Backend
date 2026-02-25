from manim import *
import random
class AraarambhTitle(Scene):
    def construct(self):
        # Set background color to a deep gradient-like dark blue
        self.camera.background_color = "#0a0e27"
        
        # Create the main title
        title = Text("Araarambh", font_size=120, weight=BOLD, font="sans-serif")
        title.set_color_by_gradient(GOLD, ORANGE, RED_E)
        
        # Create a glowing effect behind the text
        glow_circles = VGroup(*[
            Circle(radius=0.5 + i*0.3, color=GOLD, stroke_width=2, stroke_opacity=0.3-i*0.05)
            for i in range(8)
        ])
        glow_circles.move_to(ORIGIN)
        
        # Create particles that will orbit around
        particles = VGroup(*[
            Dot(radius=0.04, color=random.choice([GOLD, YELLOW, ORANGE]))
            for _ in range(30)
        ])
        
        # Position particles randomly in a circle
        for particle in particles:
            angle = random.uniform(0, TAU)
            radius = random.uniform(3, 5)
            particle.move_to([radius * np.cos(angle), radius * np.sin(angle), 0])
        
        # Create decorative lines
        lines = VGroup()
        for i in range(12):
            angle = i * TAU / 12
            line = Line(
                start=2.5 * np.array([np.cos(angle), np.sin(angle), 0]),
                end=3.5 * np.array([np.cos(angle), np.sin(angle), 0]),
                color=GOLD,
                stroke_width=3
            )
            lines.add(line)
        
        # Animation sequence
        
        # 1. Fade in glow circles from center
        self.play(
            LaggedStart(*[
                FadeIn(circle, scale=0.5)
                for circle in glow_circles
            ], lag_ratio=0.2),
            run_time=1.5
        )
        
        # 2. Rotate glow circles
        self.play(
            Rotate(glow_circles, angle=PI, run_time=2),
            rate_func=smooth
        )
        
        # 3. Bring in decorative lines with a burst effect
        self.play(
            LaggedStart(*[
                GrowFromCenter(line)
                for line in lines
            ], lag_ratio=0.1),
            run_time=1.5
        )
        
        # 4. Bring in particles
        self.play(
            LaggedStart(*[
                FadeIn(particle, scale=2)
                for particle in particles
            ], lag_ratio=0.05),
            run_time=1
        )
        
        # 5. Main title entrance - letters appear one by one with a wave effect
        title_chars = VGroup(*[Text(char, font_size=120, weight=BOLD) for char in "Araarambh"])
        title_chars.arrange(RIGHT, buff=0.1)
        title_chars.set_color_by_gradient(GOLD, ORANGE, RED_E)
        
        self.play(
            LaggedStart(*[
                FadeIn(char, shift=UP*0.5, scale=0.5)
                for char in title_chars
            ], lag_ratio=0.15),
            run_time=2
        )
        
        # 6. Pulse effect on title
        self.play(
            title_chars.animate.scale(1.15),
            rate_func=there_and_back,
            run_time=0.8
        )
        
        # 7. Create rotating animation for particles and lines
        rotating_group = VGroup(glow_circles, lines, particles)
        
        # 8. Everything rotates together while title stays prominent
        self.play(
            Rotate(rotating_group, angle=TAU, run_time=4),
            title_chars.animate.set_color_by_gradient(YELLOW, GOLD, ORANGE, RED),
            rate_func=linear
        )
        
        # 9. Create an expanding ring effect
        rings = VGroup(*[
            Circle(radius=0.1, color=GOLD, stroke_width=4)
            for _ in range(3)
        ])
        rings.move_to(ORIGIN)
        
        self.play(
            LaggedStart(*[
                AnimationGroup(
                    ring.animate.scale(50).set_stroke(opacity=0),
                )
                for ring in rings
            ], lag_ratio=0.3),
            run_time=2
        )
        
        # 10. Final emphasis - title glows and everything else fades
        self.play(
            FadeOut(glow_circles),
            FadeOut(lines),
            FadeOut(particles),
            title_chars.animate.scale(1.2).set_color(YELLOW),
            run_time=1.5
        )
        
        # 11. Add subtitle or tagline
        subtitle = Text("The Beginning", font_size=36, color=GOLD, slant=ITALIC)
        subtitle.next_to(title_chars, DOWN, buff=0.5)
        
        self.play(
            Write(subtitle),
            run_time=1.5
        )
        
        # 12. Final hold with gentle pulsing
        self.play(
            title_chars.animate.scale(1.05),
            rate_func=there_and_back_with_pause,
            run_time=2
        )
        
        self.wait(1)
        
        # 13. Fade everything out elegantly
        self.play(
            FadeOut(title_chars),
            FadeOut(subtitle),
            run_time=1.5
        )
        
        self.wait(0.5)
