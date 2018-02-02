import numpy as np
import itertools as it
import os

from PIL import Image
from colour import Color
import aggdraw

from helpers import *
from mobject import Mobject, PMobject, VMobject, \
    ImageMobject, Group, BackgroundColoredVMobject

class Camera(object):
    CONFIG = {
        "background_image" : None,
        "pixel_shape" : (DEFAULT_HEIGHT, DEFAULT_WIDTH),
        # Note 1: space_shape will be resized to match pixel_shape
        #
        # Note 2: While pixel_shape indicates the actual full height
        # and width of the pixel array, space_shape indicates only 
        # half the height and half the width of space (extending from
        # -space_height to +space_height vertically and from 
        # -space_widtdh to +space_width horizontally)
        # TODO: Rename these to SPACE_X_RADIUS, SPACE_Y_RADIUS
        "space_shape" : (SPACE_HEIGHT, SPACE_WIDTH),
        "space_center" : ORIGIN,
        "background_color" : BLACK,
        #Points in vectorized mobjects with norm greater
        #than this value will be rescaled.
        "max_allowable_norm" : 2*SPACE_WIDTH,
        "image_mode" : "RGBA",
        "n_rgb_coords" : 4,
        "background_alpha" : 0, #Out of color_max_val
        "pixel_array_dtype" : 'uint8'
    }

    def __init__(self, background = None, **kwargs):
        digest_config(self, kwargs, locals())
        self.color_max_val = np.iinfo(self.pixel_array_dtype).max
        self.init_background()
        self.resize_space_shape()
        self.reset()

    def resize_space_shape(self, fixed_dimension = 0):
        """
        Changes space_shape to match the aspect ratio 
        of pixel_shape, where fixed_dimension determines
        whether space_shape[0] (height) or space_shape[1] (width)
        remains fixed while the other changes accordingly.
        """
        aspect_ratio = float(self.pixel_shape[1])/self.pixel_shape[0]
        space_height, space_width = self.space_shape
        if fixed_dimension == 0:
            space_width = aspect_ratio*space_height
        else:
            space_height = space_width/aspect_ratio
        self.space_shape = (space_height, space_width)

    def init_background(self):
        if self.background_image is not None:
            path = get_full_raster_image_path(self.background_image)
            image = Image.open(path).convert(self.image_mode)
            height, width = self.pixel_shape
            #TODO, how to gracefully handle backgrounds 
            #with different sizes?
            self.background = np.array(image)[:height, :width]
            self.background = self.background.astype(self.pixel_array_dtype)
        else:
            background_rgba = color_to_int_rgba(
                self.background_color, alpha = self.background_alpha
            )
            self.background = np.zeros(
                list(self.pixel_shape)+[self.n_rgb_coords],
                dtype = self.pixel_array_dtype
            )
            self.background[:,:] = background_rgba

    def get_image(self):
        return Image.fromarray(
            self.pixel_array,
            mode = self.image_mode
        )

    def get_pixel_array(self):
        return self.pixel_array

    def convert_pixel_array(self, pixel_array, convert_from_floats = False):
        retval = np.array(pixel_array)
        if convert_from_floats:
            retval = np.apply_along_axis(
                lambda f : (f * self.color_max_val).astype(self.pixel_array_dtype),
                2,
                retval)
        return retval

    def set_pixel_array(self, pixel_array, convert_from_floats = False):
        self.pixel_array = self.convert_pixel_array(pixel_array, convert_from_floats)

    def set_background(self, pixel_array, convert_from_floats = False):
        self.background = self.convert_pixel_array(pixel_array, convert_from_floats)

    def set_background_from_func(self, coords_to_colors_func):
        """
        Sets background by using coords_to_colors_func to determine each pixel's color. Each input 
        to coords_to_colors_func is an (x, y) pair in space (in ordinary space coordinates; not 
        pixel coordinates), and each output is expected to be an RGBA array of 4 floats.
        """

        print "Starting set_background_from_func"

        coords = self.get_coords_of_all_pixels()
        new_background = np.apply_along_axis(
            coords_to_colors_func,
            2,
            coords
        )
        self.set_background(new_background, convert_from_floats = True)

        print "Ending set_background_from_func"

    def reset(self):
        self.set_pixel_array(self.background)

    ####

    def extract_mobject_family_members(self, mobjects, only_those_with_points = False):
        if only_those_with_points:
            method = Mobject.family_members_with_points
        else:
            method = Mobject.submobject_family
        return remove_list_redundancies(list(
            it.chain(*[
                method(m)
                for m in mobjects
                if not (isinstance(m, VMobject) and m.is_subpath)
            ])
        ))

    def get_mobjects_to_display(
        self, mobjects, 
        include_submobjects = True,
        excluded_mobjects = None,
        z_buff_func = lambda m : m.get_center()[2]
        ):
        if include_submobjects:
            mobjects = self.extract_mobject_family_members(
                mobjects, only_those_with_points = True
            )
            if excluded_mobjects:
                all_excluded = self.extract_mobject_family_members(
                    excluded_mobjects
                )
                mobjects = list_difference_update(mobjects, all_excluded)

        # Should perhaps think about what happens here when include_submobjects is False,
        # (for now, the onus is then on the caller to ensure this is handled correctly by
        # passing us an appropriately pre-flattened list of mobjects if need be)
        return sorted(mobjects, lambda a, b: cmp(z_buff_func(a), z_buff_func(b)))

    def capture_mobject(self, mobject, **kwargs):
        return self.capture_mobjects([mobject], **kwargs)

    def capture_mobjects(self, mobjects, **kwargs):
        mobjects = self.get_mobjects_to_display(mobjects, **kwargs)
        vmobjects = []
        for mobject in mobjects:
            if isinstance(mobject, VMobject) and not isinstance(mobject, BackgroundColoredVMobject):
                vmobjects.append(mobject)
            elif len(vmobjects) > 0:
                self.display_multiple_vectorized_mobjects(vmobjects)
                vmobjects = []
                
            if isinstance(mobject, BackgroundColoredVMobject):
                self.display_background_colored_vmobject(mobject)
            elif isinstance(mobject, PMobject):
                self.display_point_cloud(
                    mobject.points, mobject.rgbas, 
                    self.adjusted_thickness(mobject.stroke_width)
                )
            elif isinstance(mobject, ImageMobject):
                self.display_image_mobject(mobject)
            elif isinstance(mobject, Mobject):
                pass #Remainder of loop will handle submobjects
            else:
                raise Exception(
                    "Unknown mobject type: " + mobject.__class__.__name__
                )
            #TODO, more?  Call out if it's unknown?
        self.display_multiple_vectorized_mobjects(vmobjects)

    def display_multiple_vectorized_mobjects(self, vmobjects):
        if len(vmobjects) == 0:
            return
        #More efficient to bundle together in one "canvas"
        image = Image.fromarray(self.pixel_array, mode = self.image_mode)
        canvas = aggdraw.Draw(image)
        for vmobject in vmobjects:
            self.display_vectorized(vmobject, canvas)
        canvas.flush()

        self.pixel_array[:,:] = image

    def display_vectorized(self, vmobject, canvas):
        if vmobject.is_subpath:
            #Subpath vectorized mobjects are taken care
            #of by their parent
            return
        pen, fill = self.get_pen_and_fill(vmobject)
        pathstring = self.get_pathstring(vmobject)
        symbol = aggdraw.Symbol(pathstring)
        canvas.symbol((0, 0), symbol, pen, fill)

    def get_pen_and_fill(self, vmobject):
        pen = aggdraw.Pen(
            self.color_to_hex_l(self.get_stroke_color(vmobject)),
            max(vmobject.stroke_width, 0)
        )
        fill = aggdraw.Brush(
            self.color_to_hex_l(self.get_fill_color(vmobject)),
            opacity = int(self.color_max_val*vmobject.get_fill_opacity())
        )
        return (pen, fill)

    def color_to_hex_l(self, color):
        try:
            return color.get_hex_l()
        except:
            return Color(BLACK).get_hex_l()

    def get_stroke_color(self, vmobject):
        return vmobject.get_stroke_color()

    def get_fill_color(self, vmobject):
        return vmobject.get_fill_color()

    def get_pathstring(self, vmobject):
        result = ""        
        for mob in [vmobject]+vmobject.get_subpath_mobjects():
            points = mob.points
            # points = self.adjust_out_of_range_points(points)            
            if len(points) == 0:
                continue
            points = self.align_points_to_camera(points)
            coords = self.points_to_pixel_coords(points)
            start = "M%d %d"%tuple(coords[0])
            #(handle1, handle2, anchor) tripletes
            triplets = zip(*[
                coords[i+1::3]
                for i in range(3)
            ])
            cubics = [
                "C" + " ".join(map(str, it.chain(*triplet)))
                for triplet in triplets
            ]
            end = "Z" if vmobject.mark_paths_closed else ""
            result += " ".join([start] + cubics + [end])
        return result

    def display_background_colored_vmobject(self, cvmobject):
        mob_array = np.zeros(
            self.pixel_array.shape,
            dtype = self.pixel_array_dtype
        )
        image = Image.fromarray(mob_array, mode = self.image_mode)
        canvas = aggdraw.Draw(image)
        self.display_vectorized(cvmobject, canvas)
        canvas.flush()
        cv_background = cvmobject.background_array
        if not np.all(self.pixel_array.shape == cv_background):
            cvmobject.resize_background_array_to_match(self.pixel_array)
            cv_background = cvmobject.background_array
        array = np.array(
            (np.array(mob_array).astype('float')/255.)*\
            np.array(cv_background),
            dtype = self.pixel_array_dtype
        )
        self.pixel_array[:,:] = np.maximum(
            self.pixel_array, array
        )


    def display_point_cloud(self, points, rgbas, thickness):
        if len(points) == 0:
            return
        points = self.align_points_to_camera(points)
        pixel_coords = self.points_to_pixel_coords(points)
        pixel_coords = self.thickened_coordinates(
            pixel_coords, thickness
        )
        rgba_len = self.pixel_array.shape[2]

        rgbas = (self.color_max_val*rgbas).astype(self.pixel_array_dtype)
        target_len = len(pixel_coords)
        factor = target_len/len(rgbas)
        rgbas = np.array([rgbas]*factor).reshape((target_len, rgba_len))

        on_screen_indices = self.on_screen_pixels(pixel_coords)        
        pixel_coords = pixel_coords[on_screen_indices]        
        rgbas = rgbas[on_screen_indices]

        ph, pw = self.pixel_shape

        flattener = np.array([1, pw], dtype = 'int')
        flattener = flattener.reshape((2, 1))
        indices = np.dot(pixel_coords, flattener)[:,0]
        indices = indices.astype('int')
        
        new_pa = self.pixel_array.reshape((ph*pw, rgba_len))
        new_pa[indices] = rgbas
        self.pixel_array = new_pa.reshape((ph, pw, rgba_len))

    def display_image_mobject(self, image_mobject):
        corner_coords = self.points_to_pixel_coords(image_mobject.points)
        ul_coords, ur_coords, dl_coords = corner_coords
        right_vect = ur_coords - ul_coords
        down_vect = dl_coords - ul_coords

        impa = image_mobject.pixel_array

        oh, ow = self.pixel_array.shape[:2] #Outer width and height
        ih, iw = impa.shape[:2] #inner with and height
        rgb_len = self.pixel_array.shape[2]

        image = np.zeros((oh, ow, rgb_len), dtype = self.pixel_array_dtype)

        if right_vect[1] == 0 and down_vect[0] == 0:
            rv0 = right_vect[0]
            dv1 = down_vect[1]
            x_indices = np.arange(rv0, dtype = 'int')*iw/rv0
            y_indices = np.arange(dv1, dtype = 'int')*ih/dv1
            stretched_impa = impa[y_indices][:,x_indices]

            x0, x1 = ul_coords[0], ur_coords[0] 
            y0, y1 = ul_coords[1], dl_coords[1]
            if x0 >= ow or x1 < 0 or y0 >= oh or y1 < 0:
                return
            siy0 = max(-y0, 0) #stretched_impa y0
            siy1 = dv1 - max(y1-oh, 0)
            six0 = max(-x0, 0)
            six1 = rv0 - max(x1-ow, 0)
            x0 = max(x0, 0)
            y0 = max(y0, 0)
            image[y0:y1, x0:x1] = stretched_impa[siy0:siy1, six0:six1]
        else:
            # Alternate (slower) tactice if image is tilted
            # List of all coordinates of pixels, given as (x, y), 
            # which matches the return type of points_to_pixel_coords,
            # even though np.array indexing naturally happens as (y, x)
            all_pixel_coords = np.zeros((oh*ow, 2), dtype = 'int')
            a = np.arange(oh*ow, dtype = 'int')
            all_pixel_coords[:,0] = a%ow
            all_pixel_coords[:,1] = a/ow

            recentered_coords = all_pixel_coords - ul_coords
            coord_norms = np.linalg.norm(recentered_coords, axis = 1)

            with np.errstate(divide = 'ignore'):
                ix_coords, iy_coords = [
                    np.divide(
                        dim*np.dot(recentered_coords, vect),
                        np.dot(vect, vect),
                    )
                    for vect, dim in (right_vect, iw), (down_vect, ih)
                ]
            to_change = reduce(op.and_, [
                ix_coords >= 0, ix_coords < iw,
                iy_coords >= 0, iy_coords < ih,
            ])
            n_to_change = np.sum(to_change)
            inner_flat_coords = iw*iy_coords[to_change] + ix_coords[to_change]
            flat_impa = impa.reshape((iw*ih, rgb_len))
            target_rgbas = flat_impa[inner_flat_coords, :]

            image = image.reshape((ow*oh, rgb_len))
            image[to_change] = target_rgbas
            image = image.reshape((oh, ow, rgb_len))
        self.overlay_rgba_array(image)

    def overlay_rgba_array(self, arr):
        # """ Overlays arr onto self.pixel_array with relevant alphas"""
        bg, fg = fdiv(self.pixel_array, self.color_max_val), fdiv(arr, self.color_max_val)
        bga, fga = [arr[:,:,3:] for arr in bg, fg]
        alpha_sum = fga + (1-fga)*bga
        with np.errstate(divide = 'ignore', invalid='ignore'):
            bg[:,:,:3] = reduce(op.add, [
                np.divide(fg[:,:,:3]*fga, alpha_sum),
                np.divide(bg[:,:,:3]*(1-fga)*bga, alpha_sum),
            ])
        bg[:,:,3:] = 1 - (1 - bga)*(1 - fga)
        self.pixel_array = (self.color_max_val*bg).astype(self.pixel_array_dtype)

    def align_points_to_camera(self, points):
        ## This is where projection should live
        return points - self.space_center

    def adjust_out_of_range_points(self, points):
        if not np.any(points > self.max_allowable_norm):
            return points
        norms = np.apply_along_axis(np.linalg.norm, 1, points)
        violator_indices = norms > self.max_allowable_norm
        violators = points[violator_indices,:]
        violator_norms = norms[violator_indices]
        reshaped_norms = np.repeat(
            violator_norms.reshape((len(violator_norms), 1)), 
            points.shape[1], 1
        )
        rescaled = self.max_allowable_norm * violators / reshaped_norms
        points[violator_indices] = rescaled
        return points

    def points_to_pixel_coords(self, points):
        result = np.zeros((len(points), 2))
        ph, pw = self.pixel_shape
        sh, sw = self.space_shape
        width_mult  = pw/sw/2
        width_add   = pw/2        
        height_mult = ph/sh/2
        height_add  = ph/2
        #Flip on y-axis as you go
        height_mult *= -1

        result[:,0] = points[:,0]*width_mult + width_add
        result[:,1] = points[:,1]*height_mult + height_add
        return result.astype('int')

    def on_screen_pixels(self, pixel_coords):
        return reduce(op.and_, [
            pixel_coords[:,0] >= 0,
            pixel_coords[:,0] < self.pixel_shape[1],
            pixel_coords[:,1] >= 0,
            pixel_coords[:,1] < self.pixel_shape[0],
        ])

    def adjusted_thickness(self, thickness):
        big_shape = PRODUCTION_QUALITY_CAMERA_CONFIG["pixel_shape"]
        factor = sum(big_shape)/sum(self.pixel_shape)
        return 1 + (thickness-1)/factor

    def get_thickening_nudges(self, thickness):
        _range = range(-thickness/2+1, thickness/2+1)
        return np.array(list(it.product(_range, _range)))

    def thickened_coordinates(self, pixel_coords, thickness):
        nudges = self.get_thickening_nudges(thickness)
        pixel_coords = np.array([
            pixel_coords + nudge
            for nudge in nudges
        ])
        size = pixel_coords.size
        return pixel_coords.reshape((size/2, 2))

    def get_coords_of_all_pixels(self):
        # These are in x, y order, to help me keep things straight
        full_space_dims = np.array(self.space_shape)[::-1] * 2
        full_pixel_dims = np.array(self.pixel_shape)[::-1]

        # These are addressed in the same y, x order as in pixel_array, but the values in them
        # are listed in x, y order
        uncentered_pixel_coords = np.indices(self.pixel_shape)[::-1].transpose(1, 2, 0)
        uncentered_space_coords = fdiv(
            uncentered_pixel_coords * full_space_dims, 
            full_pixel_dims)
        # Could structure above line's computation slightly differently, but figured (without much 
        # thought) multiplying by space_shape first, THEN dividing by pixel_shape, is probably 
        # better than the other order, for avoiding underflow quantization in the division (whereas 
        # overflow is unlikely to be a problem)

        centered_space_coords = (uncentered_space_coords - fdiv(full_space_dims, 2))

        # Have to also flip the y coordinates to account for pixel array being listed in 
        # top-to-bottom order, opposite of screen coordinate convention
        centered_space_coords = centered_space_coords * (1, -1)

        return centered_space_coords

class MovingCamera(Camera):
    """
    Stays in line with the height, width and position
    of a given mobject
    """
    CONFIG = {
        "aligned_dimension" : "width" #or height
    }
    def __init__(self, mobject, **kwargs):
        digest_locals(self)
        Camera.__init__(self, **kwargs)

    def capture_mobjects(self, *args, **kwargs):
        self.space_center = self.mobject.get_center()
        self.realign_space_shape()        
        Camera.capture_mobjects(self, *args, **kwargs)

    def realign_space_shape(self):
        height, width = self.space_shape
        if self.aligned_dimension == "height":
            self.space_shape = (self.mobject.get_height()/2, width)
        else:
            self.space_shape = (height, self.mobject.get_width()/2)
        self.resize_space_shape(
            0 if self.aligned_dimension == "height" else 1
        )


class MappingCamera(Camera):
    CONFIG = {
        "mapping_func" : lambda p : p,
        "min_anchor_points" : 50,
        "allow_object_intrusion" : False
    }

    def points_to_pixel_coords(self, points):
        return Camera.points_to_pixel_coords(self, np.apply_along_axis(self.mapping_func, 1, points))
    
    def capture_mobjects(self, mobjects, **kwargs):
        mobjects = self.get_mobjects_to_display(mobjects, **kwargs)
        if self.allow_object_intrusion:
            mobject_copies = mobjects
        else:
            mobject_copies = [mobject.copy() for mobject in mobjects]
        for mobject in mobject_copies:
            if isinstance(mobject, VMobject) and \
            0 < mobject.get_num_anchor_points() < self.min_anchor_points:
                mobject.insert_n_anchor_points(self.min_anchor_points)
        Camera.capture_mobjects(
            self, mobject_copies, 
            include_submobjects = False,
            excluded_mobjects = None,
        )

# Note: This allows layering of multiple cameras onto the same portion of the pixel array,
# the later cameras overwriting the former
#
# TODO: Add optional separator borders between cameras (or perhaps peel this off into a 
# CameraPlusOverlay class)
class MultiCamera(Camera):
    def __init__(self, *cameras_with_start_positions, **kwargs):
        self.shifted_cameras = [
            DictAsObject(
            {
                "camera" : camera_with_start_positions[0], 
                "start_x" : camera_with_start_positions[1][1],
                "start_y" : camera_with_start_positions[1][0],
                "end_x" : camera_with_start_positions[1][1] + camera_with_start_positions[0].pixel_shape[1],
                "end_y" : camera_with_start_positions[1][0] + camera_with_start_positions[0].pixel_shape[0],
            })
            for camera_with_start_positions in cameras_with_start_positions
        ]
        Camera.__init__(self, **kwargs)

    def capture_mobjects(self, mobjects, **kwargs):
        for shifted_camera in self.shifted_cameras:
            shifted_camera.camera.capture_mobjects(mobjects, **kwargs)
            
            self.pixel_array[
                shifted_camera.start_y:shifted_camera.end_y, 
                shifted_camera.start_x:shifted_camera.end_x] \
            = shifted_camera.camera.pixel_array

    def set_background(self, pixel_array, **kwargs):
        for shifted_camera in self.shifted_cameras:
            shifted_camera.camera.set_background(
                pixel_array[
                    shifted_camera.start_y:shifted_camera.end_y, 
                    shifted_camera.start_x:shifted_camera.end_x],
                **kwargs
            )

    def set_pixel_array(self, pixel_array, **kwargs):
        Camera.set_pixel_array(self, pixel_array, **kwargs)
        for shifted_camera in self.shifted_cameras:
            shifted_camera.camera.set_pixel_array(
                pixel_array[
                    shifted_camera.start_y:shifted_camera.end_y, 
                    shifted_camera.start_x:shifted_camera.end_x],
                **kwargs
            )

    def init_background(self):
        Camera.init_background(self)
        for shifted_camera in self.shifted_cameras:
            shifted_camera.camera.init_background()

# A MultiCamera which, when called with two full-size cameras, initializes itself
# as a splitscreen, also taking care to resize each individual camera within it
class SplitScreenCamera(MultiCamera):
    def __init__(self, left_camera, right_camera, **kwargs):
        digest_config(self, kwargs)
        self.left_camera = left_camera
        self.right_camera = right_camera
        
        half_width = self.pixel_shape[1] / 2
        for camera in [self.left_camera, self.right_camera]:
            camera.pixel_shape = (self.pixel_shape[0], half_width) # TODO: Round up on one if width is odd
            camera.init_background()
            camera.resize_space_shape()
            camera.reset()

        MultiCamera.__init__(self, (left_camera, (0, 0)), (right_camera, (0, half_width)))


