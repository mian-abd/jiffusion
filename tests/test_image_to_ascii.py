from pathlib import Path
import tempfile
import unittest

from PIL import Image

from image_to_ascii import to_ascii, write_example
from prompts import PALETTE


class ConversionTests(unittest.TestCase):
    def test_five_brightness_levels_and_quantization_boundaries(self):
        for values, expected in [
            ([255, 191, 128, 64, 0], ".:-=#"),
            ([255, 224, 223, 160, 159, 96, 95, 32, 31, 0], "..::--==##"),
        ]:
            size = len(values)
            image = Image.new("L", (size, size))
            image.putdata(values * size)
            self.assertEqual(to_ascii(image, size).splitlines(), [expected] * size)

    def test_full_grayscale_range_uses_only_five_symbols(self):
        image = Image.new("L", (16, 16))
        image.putdata(range(256))
        text = to_ascii(image, 16)
        self.assertEqual(set(text.replace("\n", "")), set(PALETTE))
        self.assertEqual(text[0], "#")
        self.assertEqual(text[-1], ".")

    def test_wide_image_is_centered_without_stretching_or_cropping(self):
        rows = to_ascii(Image.new("RGB", (40, 20), "black")).splitlines()
        self.assertEqual(rows, ["." * 20] * 5 + ["#" * 20] * 10 + ["." * 20] * 5)

    def test_transparency_is_composited_onto_white(self):
        clear = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        translucent = Image.new("RGBA", (4, 4), (0, 0, 0, 128))
        self.assertEqual(to_ascii(clear, 4).splitlines(), ["...."] * 4)
        self.assertEqual(to_ascii(translucent, 4).splitlines(), ["----"] * 4)

    def test_exif_rotation_is_applied_before_fitting(self):
        image = Image.new("RGB", (2, 4), "black")
        image.getexif()[274] = 6
        self.assertEqual(to_ascii(image, 4).splitlines(), ["....", "####", "####", "...."])

    def test_extremely_thin_image_still_has_a_pixel_of_width(self):
        rows = to_ascii(Image.new("RGB", (1, 1000), "black")).splitlines()
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(len(row) == 20 and row.count("#") == 1 for row in rows))

    def test_record_format_and_duplicate_id_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "source.png"
            Image.new("RGB", (2, 2), "black").save(source)
            output_dir = directory / "gold"
            output = write_example(source, prompt="a duck", example_id=1, size=2, output_dir=output_dir)
            self.assertEqual(output.name, "001-a-duck.txt")
            self.assertEqual(output.read_bytes(), b"a duck\n##\n##\n")
            with self.assertRaises(FileExistsError):
                write_example(source, prompt="a different duck", example_id=1, output_dir=output_dir)
            self.assertEqual(output.read_bytes(), b"a duck\n##\n##\n")

    def test_duplicate_id_in_a_nested_batch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            batch = output_dir / "shapes-250"
            batch.mkdir()
            (batch / "013-a-circle.txt").write_text("a circle\n##\n##\n")
            with self.assertRaises(FileExistsError):
                write_example("unused.png", prompt="a duck", example_id=13, output_dir=output_dir)

    def test_invalid_prompt_and_size_are_rejected(self):
        with self.assertRaises(ValueError):
            to_ascii(Image.new("L", (1, 1)), 0)
        for prompt in ("", " ", "a duck\nextra", "a duck\rextra"):
            with self.assertRaises(ValueError):
                write_example("unused.png", prompt=prompt, example_id=1)


if __name__ == "__main__":
    unittest.main()
