# -*- coding: utf8 -*-
# Blender WCP IFF mesh import/export script by Kevin Caccamo
# Copyright © 2013-2016 Kevin Caccamo
# E-mail: kevin@ciinet.org
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
#
# <pep8-80 compliant>

import bpy
import mathutils
import warnings
import re
import array
import time
from os import sep as dirsep
from . import iff_mesh
from math import sin, cos
from collections import OrderedDict
from itertools import repeat, starmap

LFLAG_UNKNOWN1 = 1
LFLAG_FULLBRIGHT = 2
LFLAG_UNKNOWN2 = 8

# Name pattern for LOD objects. Largely deprecated in favour of named LOD
# object models. Mostly present for backwards compatibility.
# Group 1 is the prefix.
# Group 2 is the LOD level number.
# Group 3 is the suffix.
MAIN_LOD_RE = re.compile(r"^(detail-?)(\d+)(\.\d+)?$")

# Name pattern for LOD objects, grouped by name.
# Group 1 is the prefix object name.
# Group 2 is the LOD level number.
# Group 3 is the suffix.
CHLD_LOD_RE = re.compile(r"^([\w#]+-lod)(\d+)(\.\d+)?$")

# Name pattern for hardpoints. Group 1 is the hardpoint name, group 2 is
# the suffix appended by Blender to objects with conflicting names.
HARDPOINT_RE = re.compile(r"^hp-(\w+)(?:\.\d*)?$")

# Non-critical warnings will be reported to Blender. Critical errors will be
# exceptions.


class KeyWarning(Warning):
    pass


class TypeWarning(Warning):
    pass


class ValueWarning(Warning):
    pass


class ModelManager:
    # Manages the LODs for a mesh to export.
    # Each instance of this class should be exportable to a mesh IFF.
    # Scans for a base LOD mesh and other related LODs in a given scene.

    # One of the asteroid models I've looked at (AST_G_01.IFF) has 7 LODs
    MAX_NUM_LODS = 7

    # The LOD base object uses the 'detail-X' naming scheme.
    # LOD_NSCHEME_DETAIL = 0

    # The LOD base object used the 'Y-lodX' naming scheme.
    # LOD_NSCHEME_CHLD = 1

    # Name pattern for LOD range info. Group 1 is the range, group 2 is the
    # suffix appended by Blender to objects with conflicting names.
    DRANGE_RE = re.compile(r"^drang=([0-9,]+)(?:\.\d*)?$")

    # prefix for CNTR/RADI spheres
    CNTRADI_PFX = "cntradi"

    # prefix for spherical collider definition objects
    COLLSPHR_PFX = "collsphr"

    # prefix for BSP collider definition objects
    COLLMESH_PFX = "collmesh"

    def __init__(self, base_name, base_obj, use_facetex, drang_increment,
                 gen_bsp, scene_name):

        if not isinstance(base_name, str):
            raise TypeError("Model name must be a string!")
        if scene_name not in bpy.data.scenes:
            raise TypeError("scene must be the name of a Blender scene!")
        if base_obj not in bpy.data.scenes[scene_name].objects:
            raise TypeError("base_obj must be the name of a Blender mesh "
                            "object in the given scene!")

        self.scene = scene_name  # Name of the scene to use
        # self.base_name = base_name
        self._exp_fname = base_name  # Export filename
        # self.name_scheme = 0  # See LOD_NSCHEME constants above
        self.modelname = base_name  # Model base name (ex. Duhiky)
        self.base_obj = base_obj  # Name of base object (ex. Duhiky-lod0)
        self.base_prefix = ""  # Prefix before LOD level number.
        self.base_suffix = ""  # Object name suffix (.000, .001, etc.)
        self.base_parent = str(
            bpy.data.scenes[scene_name].objects[base_obj].parent)
        self.base_lod = self._get_lod(base_obj, True)  # Get base object LOD

        # Names of LOD objects
        self.lods = [None for x in range(self.MAX_NUM_LODS)]

        self.lodms = []  # LOD object meshes (converted from objects)
        self.lods[self.base_lod] = base_obj
        self.hardpoints = []  # Hardpoints
        self.hpobnames = []  # Hardpoint Blender object names

        # LOD ranges (RANG chunk)
        self.dranges = [None for x in range(self.MAX_NUM_LODS)]
        self.dranges[0] = 0.0
        self.drang_increment = drang_increment

        # CNTR/RADI spheres for each LOD.
        self.dsphrs = [None for x in range(self.MAX_NUM_LODS)]

        self.gen_bsp = gen_bsp
        self.collider = None  # COLL form
        self.use_mtltex = not use_facetex
        self.textures = []  # Textures for all LODs
        self.mtltexs = {}  # Material -> texture dict
        self.children = []  # Child objects
        self.setup_complete = False

    def _get_lod(self, lod_obj, base=False):
        lod_match = MAIN_LOD_RE.match(lod_obj)
        if lod_match:
            if base:
                # self.name_scheme = self.LOD_NSCHEME_DETAIL
                self.base_prefix = lod_match.group(1)
                self.base_suffix = lod_match.group(3)
                if self.base_suffix is None: self.base_suffix = ""
                warnings.warn("detail-x LOD naming scheme is deprecated.",
                              DeprecationWarning)
            lod_lev = int(lod_match.group(2))
            return lod_lev

        lod_match = CHLD_LOD_RE.match(lod_obj)
        if lod_match:
            if base:
                # self.name_scheme = self.LOD_NSCHEME_CHLD
                base_prefix = lod_match.group(1)
                self.modelname = base_prefix[:base_prefix.rindex("-")]
                self.base_prefix = base_prefix
                self.base_suffix = lod_match.group(3)
                if self.base_suffix is None: self.base_suffix = ""
            lod_lev = int(lod_match.group(2))
            return lod_lev

        # Assume LOD 0, and "child" LOD naming scheme
        if base:
            if self.modelname.rfind(".") > 0:
                self.base_suffix = self.modelname[self.modelname.rfind("."):]
                self.modelname = self.modelname[:self.modelname.rfind(".")]
            self.base_prefix = self.modelname + "-lod"
        return 0

    def texs_for_mtl(self, material):
        if not isinstance(material, bpy.types.Material):
            raise TypeError("You must provide a Blender material in order to "
                            "get its valid textures!")

        filled_slots = 0
        valid_slots = []
        for ts in material.texture_slots:
            if ts is not None:
                filled_slots += 1
                if (isinstance(ts, bpy.types.MaterialTextureSlot) and
                    ts.texture_coords == "UV" and
                    isinstance(ts.texture, bpy.types.ImageTexture) and
                        ts.texture.image is not None):
                    valid_slots.append(ts.texture)

        if filled_slots > 0 and len(valid_slots) == 0:
            raise ValueError(
                "Found no valid texture slots for the material '{}' out of "
                "the ones that were filled! In order for a texture slot to be "
                "valid, it must be a UV-mapped image texture."
                .format(material.name))

        return valid_slots

    def setup(self):
        print(banner(self.modelname, 70))
        # Scan for valid LOD objects related to the base LOD object
        for lod in range(self.MAX_NUM_LODS):
            lod_name = "{}{}{}".format(self.base_prefix, lod, self.base_suffix)

            lobj = None
            try:
                lobj = bpy.data.scenes[self.scene].objects[lod_name]
            except KeyError:
                lobj = None
                del self.dranges[-1]
                del self.dsphrs[-1]
            if lobj is not None and lod_name != self.base_obj:
                if self.lods[lod] is None:
                    if lobj.type == "MESH" or lobj.type == "EMPTY":
                        if lobj.hide is False:

                            if str(lobj.parent) != self.base_parent:
                                raise ValueError(
                                    "LOD {} ({}) has a different parent than "
                                    "LOD {} ({})!".format(
                                        lod, lobj,
                                        self.base_lod, self.base_parent))

                            self.lods[lod] = lod_name

                    else:
                        raise TypeError("Object {} is not a mesh or empty!"
                                        .format(lod_name))
                else:
                    raise ValueError(
                        "Tried to set LOD {} to object {}, but it was already "
                        "set to object {}!".format(lod, lod_name,
                                                   self.lods[lod]))

        # Ensure the LODs array is consistent
        if self.lods[0] is None:
            raise TypeError("The first LOD (LOD 0) of the model must exist!")

        no_lod_idx = None  # Index for first blank LOD

        for lod_idx, lod_obj in enumerate(self.lods):
            if no_lod_idx is None:
                if lod_obj is None:
                    no_lod_idx = lod_idx
            else:
                if lod_obj is not None:
                    raise TypeError(
                        "Inconsistent LODs. A LOD object was found after lod "
                        "{} ({}).".format(no_lod_idx, lod_obj))

        if no_lod_idx is not None:
            self.lods = self.lods[:no_lod_idx]

        del no_lod_idx

        print("LOD object names:", self.lods)

        # The collider for the lowest (most detailed) LOD takes precedence over
        # colliders for other LODs, and a model can only have one collider.
        collider_lod = self.MAX_NUM_LODS + 1

        # LOD ranges can be either a custom property of the LOD object, or the
        # name of an empty object parented to said LOD object. The custom
        # property takes precedence, however.
        drange_prop = [False for x in range(len(self.lods))]

        for obj in bpy.data.scenes[self.scene].objects:
            if obj.parent is not None and obj.parent.name in self.lods:
                par_lod = int(obj.parent.name[-1])
                if obj.type == "EMPTY" and obj.hide is False:

                    if self.DRANGE_RE.match(obj.name) and par_lod > 0:
                        # LOD Range object
                        if drange_prop[par_lod] is False:
                            drange = self.DRANGE_RE.match(obj.name).group(1)
                            # A comma is used in place of a period in the
                            # drange object name because Blender likes to add
                            # .000, .001, etc. to objects with duplicate names.
                            drange = float(drange.translate({44: 46}))
                            self.dranges[par_lod] = drange

                    elif (obj.name.lower().startswith(self.CNTRADI_PFX) and
                          obj.empty_draw_type == "SPHERE"):
                        # CNTR/RADI object
                        x, z, y = obj.location
                        self.dsphrs[par_lod] = iff_mesh.Sphere(
                            x, y, z, max(obj.scale)
                        )

                    elif (obj.name.lower().startswith(self.COLLSPHR_PFX) and
                          obj.empty_draw_type == "SPHERE"):
                        # COLLSPHR object
                        if par_lod < collider_lod:
                            x, z, y = obj.location
                            self.collider = iff_mesh.Collider(
                                "sphere",
                                iff_mesh.Sphere(x, y, z, max(obj.scale))
                            )
                            collider_lod = par_lod

                    elif HARDPOINT_RE.match(obj.name):
                        # Hardpoint object
                        hpname = HARDPOINT_RE.match(obj.name).group(1)
                        hpmatrix = obj.rotation_euler.to_matrix().to_3x3()
                        hardpt = iff_mesh.Hardpoint(hpmatrix, obj.location,
                                                    hpname)
                        self.hardpoints.append(hardpt)
                        self.hpobnames.append(obj.name)

            elif obj.name in self.lods:
                obj_lod = self.lods.index(obj.name)
                if obj_lod > 0:
                    # LOD range for LOD 0 is always ignored; it is always 0.
                    drange = obj.get("drange")
                    if drange is not None:
                        self.dranges[obj_lod] = drange
                        drange_prop[obj_lod] = True
                        continue

        del collider_lod
        del drange_prop

        print("dranges (b4):", self.dranges)

        # Fill in blank LOD ranges
        for dr_idxa in range(len(self.dranges)):
            if self.dranges[dr_idxa] is None:
                drange_before = self.dranges[dr_idxa - 1]
                empty_dranges = 0

                # Find closest value for drange_after
                for dr_idxb in range(dr_idxa, len(self.dranges)):
                    if self.dranges[dr_idxb] is not None:
                        break
                    else:
                        empty_dranges += 1

                try:
                    drange_after = self.dranges[dr_idxa + empty_dranges]
                except IndexError:
                    # There's no known detail ranges after this one,
                    # so generate them
                    drange_after = (self.drang_increment *
                                    (empty_dranges + 1) + drange_before)

                if drange_after < drange_before:
                    raise ValueError("Each detail range must be greater than "
                                     "the one before it!")

                # Find interval and index of last detail range
                drange_interval = (
                    (drange_after - drange_before) /
                    (empty_dranges + 1))

                dridx_end = dr_idxa + empty_dranges

                # Fill in the missing values
                # Best list comprehension ever LOL.
                self.dranges[dr_idxa:dridx_end] = [
                    x * n + drange_before for x, n in zip(
                        repeat(drange_interval, empty_dranges),
                        range(1, empty_dranges + 1)
                    )]

        print("dranges (after):", self.dranges)

        # Generate CNTR/RADI data for each LOD where it does not exist.
        for lod_idx in range(len(self.dsphrs)):
            if self.dsphrs[lod_idx] is None:
                lod_obj = (
                    bpy.data.scenes[self.scene].objects[self.lods[lod_idx]])

                x, z, y = lod_obj.location
                r = max(lod_obj.dimensions) / 2
                self.dsphrs[lod_idx] = iff_mesh.Sphere(x, y, z, r)

            print("LOD {} CNTR/RADI: {}".format(lod_idx, self.dsphrs[lod_idx]))

        # Ensure there are no hardpoint name conflicts
        hpnames = []
        for hp in self.hardpoints:
            if hp.name in hpnames:
                raise ValueError(
                    "Two or more hardpoints of the object {} have the same "
                    "name ({})! (Hardpoint name is stripped of numeric "
                    "suffix)".format(self.modelname, hp.name))
            hpnames.append(hp.name)
        del hpnames

        print("========== Hardpoints ==========")
        for hp, hpob in zip(self.hardpoints, self.hpobnames):
            print(hp, ": ({})".format(hpob))

        # Generate the collider for this model if it doesn't exist.
        if self.collider is None:
            lod_obj = bpy.data.scenes[self.scene].objects[self.lods[0]]
            x, z, y = lod_obj.location
            radius = max(lod_obj.dimensions) / 2
            self.collider = iff_mesh.Collider(
                "sphere", iff_mesh.Sphere(x, y, z, radius)
            )

        print("Collider:", self.collider)

        # Convert all LOD objects to meshes to populate the LOD mesh list.
        for lod in self.lods:
            try:
                self.lodms.append(
                    bpy.data.scenes[self.scene].objects[lod].to_mesh(
                        bpy.data.scenes[self.scene], True, "PREVIEW")
                )
            except RuntimeError:
                print("Object {} is an empty.".format(lod))
                # self.lodms.append(None)

        # Get the textures used by all LODs for this model
        used_materials = []
        for lodm in self.lodms:
            lodm.calc_tessface()
            # tf_mtl = None  # The material for this tessface
            # tf_mlf = 0  # The light flags for this tessface
            # tf_mtf = False  # Is the material a flat colour
            if self.use_mtltex:
                # Material textures
                for tf in lodm.tessfaces:
                    # Ensure material for this face exists
                    try:
                        tf_mtl = lodm.materials[tf.material_index]
                    except IndexError:
                        raise ValueError("You must have a valid material "
                                         "assigned to each face!")

                    if tf_mtl not in used_materials:
                        used_materials.append(tf_mtl)
            else:
                # Face textures (visible in Multitexture viewport render mode)
                for tf, tfuv in zip(
                        lodm.tessfaces,
                        lodm.tessface_uv_textures.active.data):
                    if (tfuv.image is not None and
                            tfuv.image not in used_materials):
                        # Use the face image
                        used_materials.append(tfuv.image)
                    else:
                        # Use the face material colour
                        tf_mtl = lodm.materials[tf.material_index]
                        tf_clr = iff_mesh.colour_texnum(tf_mtl.diffuse_color)

                        if tf_clr not in used_materials:
                            used_materials.append(tf_clr)

        # Get information about materials.
        # TODO: Find out how best to associate the new materials with the
        # individual faces.
        # REVIEW: Ensure all "mtldata" tuples use the same format.
        if self.use_mtltex:
            for tf_mtl in used_materials:

                # Get light flags for this material
                if tf_mtl.get("light_flags") is not None:
                    tf_mlf = int(tf_mtl.get("light_flags"))
                elif tf_mtl.use_shadeless:
                    tf_mlf = LFLAG_FULLBRIGHT
                else:
                    tf_mlf = 0

                tf_mtexs = self.texs_for_mtl(tf_mtl)  # Valid texture slots

                if len(tf_mtexs) == 0:
                    # Flat colour material; Use the colour of the material.
                    tf_mtf = True
                    tf_img = iff_mesh.colour_texnum(tf_mtl.diffuse_color)
                else:
                    # Textured material; Use first valid texture slot.
                    tf_mtf = False
                    tf_img = tf_mtexs[0].image

                mtldata = (tf_mtf, tf_mlf, tf_img)
                if mtldata not in self.textures:
                    self.mtltexs[tf_mtl] = len(self.textures)
                    self.textures.append(mtldata)
        else:
            for tf_mtl in used_materials:
                tf_mlf = 0
                tf_mtf = True if isinstance(tf_mtl, int) else False

                mtldata = (tf_mtf, tf_mlf, tf_img)
                if mtldata not in self.textures:
                    self.mtltexs[tf_mtl] = len(self.textures)
                    self.textures.append(mtldata)

        print("Materials used by this model:")
        for mtl in self.textures:
            print(mtl[2], "Light flags:", mtl[1],
                  "(Flat)" if mtl[0] else "(Textured)")

        self.setup_complete = True

    @property
    def exp_fname(self):
        """The export filename.

        The model is written to disk with this filename, suffixed by '.iff'
        For example, if the export filename is 'Duhiky', the file for this
        model will be 'Duhiky.iff'"""
        return self._exp_fname

    @exp_fname.setter
    def exp_fname(self, value):
        if not isinstance(value, str):
            raise TypeError("Export filename must be a string!")

        self._exp_fname = value

    @exp_fname.deleter
    def exp_fname(self):
        self._exp_fname = self.modelname


class ExportBackend:

    def __init__(self,
                 filepath,
                 start_texnum=22000,
                 apply_modifiers=True,
                 export_active_only=True,
                 use_facetex=False,
                 wc_orientation_matrix=None,
                 include_far_chunk=True,
                 drang_increment=500.0,
                 generate_bsp=False):
        self.filepath = filepath
        self.start_texnum = start_texnum
        self.apply_modifiers = apply_modifiers
        self.export_active_only = export_active_only
        self.use_facetex = use_facetex
        self.wc_orientation_matrix = wc_orientation_matrix
        self.include_far_chunk = include_far_chunk
        self.drang_incval = drang_increment
        self.generate_bsp = generate_bsp
        self.modelname = ""

    def calc_dplane(self, vert, facenrm):
        """Calculate the D-Plane of the face.

        vert refers to the first vertex of the face
        facenrm refers to the face normal
        The D-Plane is used by the VISION engine for backface culling
        Thanks to gr1mre4per from CIC for the algorithm!
        """
        dplane = -((facenrm[0] * vert[0]) +
                   (facenrm[1] * vert[1]) +
                   (facenrm[2] * vert[2]))
        return dplane

    def get_materials(self):
        """Convert all of the named material textures to
        texture indices.

        Returns a mapping from material texture filenames
        to texture indices."""
        # Aliases to long function names
        # Filename w/o extension
        get_fname = bpy.path.display_name_from_filepath
        # Filename with extension
        get_bname = bpy.path.basename

        num_lods = lod_data["num_lods"]
        # Use OrderedDict to retain order of texture -> texnum
        # Texture filename -> texture number mapping
        mtl_texnums = OrderedDict()
        # Materials used by the mesh
        used_mtls = []

        # Get all of the material names used in each LOD mesh.
        for lod in range(num_lods):
            mesh = lod_data["LOD-" + str(lod)].to_mesh(
                bpy.context.scene, self.apply_modifiers, "PREVIEW")
            if self.use_facetex:
                active_idx = None
                for idx, texmap in enumerate(mesh.tessface_uv_textures):
                    if texmap.active:
                        active_idx = idx
                        break
                for f in mesh.tessface_uv_textures[active_idx].data:
                    used_mtls.append(get_bname(f.image.filepath))
            else:
                for f in mesh.tessfaces:
                    cur_mtl = mesh.materials[f.material_index].name
                    if cur_mtl not in used_mtls:
                        used_mtls.append(cur_mtl)

        # Get the textures and associate each texture with a material number,
        # beginning at the user's specified starting texture number.
        num_textures = 0
        for mtl_name in used_mtls:
            curr_txnum = self.start_texnum + num_textures
            if self.use_facetex:
                img_bname = get_bname(mtl_name)
                img_fname = get_fname(mtl_name)
                print(img_fname)
                if img_fname.isnumeric():
                    # If the filename is numeric, use it as the
                    # texture index.
                    img_num = int(img_fname)
                    if img_num >= 0 and img_num <= 99999990:
                        if img_num != curr_txnum:
                            mtl_texnums[img_bname] = img_num
                        else:
                            mtl_texnums[img_bname] = curr_txnum
                            print(img_fname, "is already in use! Using",
                                  curr_txnum, "instead.")
                            num_textures += 1
                else:
                    if img_bname not in mtl_texnums.keys():
                        mtl_texnums[img_bname] = curr_txnum
                        num_textures += 1
            else:
                curr_mtl = bpy.data.materials[mtl_name]
                curr_tx = self.get_first_texture_slot(curr_mtl).texture

                if curr_tx.type == "IMAGE":
                    img_bname = get_bname(curr_tx.image.filepath)
                    img_fname = get_fname(curr_tx.image.filepath)
                    if img_fname.isnumeric():
                        # If the filename is numeric, use it as the
                        # texture index.
                        img_num = int(img_fname)
                        if img_num >= 0 and img_num <= 99999990:
                            # What if the user has two numeric image
                            # filenames that are the same number?
                            # i.e. 424242.jpg and 424242.png
                            if img_num not in mtl_texnums.values():
                                mtl_texnums[img_bname] = img_num
                            else:
                                mtl_texnums[img_bname] = curr_txnum
                                print(img_fname, "is already in use! Using",
                                      curr_txnum, "instead.")
                                num_textures += 1
                        else:
                            # If the number is too big,
                            # use the "default" value.
                            mtl_texnums[img_bname] = curr_txnum
                            print(img_fname, "is too big a number",
                                  "to be used as a texture number! Using",
                                  curr_txnum, "instead.")
                            num_textures += 1
                    # If the image filename is not numeric,
                    # refer to the user's starting texture number.
                    else:
                        if img_bname not in mtl_texnums.keys():
                            mtl_texnums[img_bname] = curr_txnum
                            num_textures += 1
                else:
                    error_msg = curr_tx.name + " is not an image texture."
                    raise TypeError(error_msg)
        return mtl_texnums

    def get_txinfo(self, mtl_texnums, as_comment=False):
        """Gets a string showing the Image Filename->Texture number"""
        # Used to make the Image Filename->Material Number list
        # easier to read.
        # max_width = len(max(mtl_texnums.keys(), key=len))
        # Print Image Filename->Material Number information for the
        # user to use as a guide for converting textures.
        tx_info = ""
        for img_fname, texnum in sorted(
                mtl_texnums.items(),
                key=lambda mattex: mattex[1]):
            if as_comment:
                tx_info += "// "
            maxlen = max(map(len, mtl_texnums.keys()))
            tx_info += (
                "{:" + str(maxlen) +
                "} --> {!s:0>8}.mat\n").format(img_fname, texnum)
        return tx_info


class HierarchyManager:
    """A valid object, and its valid children."""

    def __init__(self, root_obj, modelname, modeldir, use_facetex,
                 drang_increment, generate_bsp, scene_name):

        self.root_obj = root_obj

        self.modelname = modelname  # The filename the user specified.
        self.modeldir = modeldir
        self.use_facetex = use_facetex
        self.drang_incval = drang_increment
        self.generate_bsp = generate_bsp
        self.scene_name = scene_name
        self.managers = []

        self.main_lods_used = set()
        self.hierarchy_objects = self.get_children(root_obj)

    def is_valid_obj(self, obj, parent=None):
        """Ensure the object in question is valid for exporting."""
        if not (str(obj.parent) == str(parent) and obj.hide is False and
                (obj.type == "MESH" or obj.type == "EMPTY")):
            return False

        if CHLD_LOD_RE.match(obj.name):
            return True
        elif MAIN_LOD_RE.match(obj.name):
            lod_lev = int(MAIN_LOD_RE.match(obj.name).group(2))
            if lod_lev in self.main_lods_used:
                raise ValueError("You cannot have more than one detail-x "
                                 "object in a hierarchy tree!")
            elif len(self.main_lods_used) > 0:
                return False
            self.main_lods_used.add(lod_lev)
            print("main_lods_used:", self.main_lods_used)
            return True

    def get_children(self, obj):
        """Get a list of the object, and all of its exportable children.

        In order for a child object to be exportable, it must be:
        1. Parented to another valid LOD object or hardpoint.
        2. Named such that MAIN_LOD_RE or CHLD_LOD_RE matches its name.
        3. Visible in Blender's viewport."""
        # List containing an object and its children.
        objects = [obj]
        obj_main = MAIN_LOD_RE.match(obj.name)
        if obj_main:
            self.main_lods_used.add(int(obj_main.group(2)))

        def is_valid_hp(obj, parent=None):
            return (str(obj.parent) == str(parent) and obj.hide is False and
                    obj.type == "EMPTY" and HARDPOINT_RE.match(obj.name))

        # def info_for(obj):
        #     if is_valid_obj(obj):
        #         obj_match = CHLD_LOD_RE.match(obj.name)
        #         if obj_match:
        #             obj_bname = obj_match.group(1)
        #         else:
        #             obj_match = MAIN_LOD_RE.match(obj.name)
        #             obj_bname = self.modelname
        #
        #         return obj.name, obj_bname

        def children_of(parent_obj):
            """Get the valid child objects for a parent object.

            Child objects may be parented directly to the object, or to one of
            the hardpoints."""
            childnames = []
            children = []
            parent_hps = []
            for obj in bpy.context.scene.objects:
                if self.is_valid_obj(obj, parent_obj):
                    obj_bname = CHLD_LOD_RE.match(obj.name)
                    if obj_bname:
                        obj_bname = obj_bname.group(1)
                    else:
                        obj_bname = self.modelname
                    if obj_bname not in childnames:
                        childnames.append(obj_bname)
                        children.append(obj)
                if is_valid_hp(obj, parent_obj) and obj not in parent_hps:
                    parent_hps.append(obj)

            for obj in bpy.context.scene.objects:
                for hp in parent_hps:
                    if self.is_valid_obj(obj, hp):
                        obj_bname = CHLD_LOD_RE.match(obj.name)
                        if obj_bname:
                            obj_bname = obj_bname.group(1)
                        else:
                            obj_bname = self.modelname
                        if obj_bname not in childnames:
                            childnames.append(obj_bname)
                            children.append(obj)

            if len(children) == 0:
                return children
            else:
                for obj in children:
                    children.extend(children_of(obj))

                return children

        objects.extend(children_of(obj))

        # import code
        # code.interact(banner="Entering REPL (L721).", local=locals())

        return objects

    def hierarchy_str_for(self, obj):
        """Get the export filename for the object.

        This function should be called after objects have been selected for
        export."""

        def parents_of(obj):
            rv = [obj]

            if (obj.name == self.root_obj.name):
                return rv

            elif (obj.parent is not None and (obj.parent.type == "MESH" or
                  obj.parent.type == "EMPTY") and
                  (MAIN_LOD_RE.match(obj.parent.name) or
                   CHLD_LOD_RE.match(obj.parent.name)) and
                  obj.parent.hide is False):
                rv.extend(parents_of(obj.parent))

            elif (obj.parent is not None and obj.parent.type == "EMPTY" and
                  HARDPOINT_RE.match(obj.parent.name) and
                  obj.parent.hide is False):
                rv.extend(parents_of(obj.parent.parent))

            return rv

        def name_of(obj, first):
            if obj is not None:
                obj_ch_name = CHLD_LOD_RE.match(obj.name)

                if MAIN_LOD_RE.match(obj.name):
                    return self.modelname

                elif obj_ch_name:
                    if (first and obj.name == self.root_obj.name and
                            not self.main_lods_used):
                        return self.modelname
                    else:
                        obj_mname = obj_ch_name.group(1)
                        obj_mname = obj_mname[:obj_mname.rindex("-")]
                        return obj_mname

                else:
                    if first:
                        return self.modelname
                    obj_mname = obj.name
                    if obj_mname.rfind(".") > 0:
                        return obj_mname[:obj_mname.rfind(".")]
                    else:
                        return obj_mname

        if obj.parent is not None:
            hierarchy = parents_of(obj)
            hierarchy = [(ob, idx == 0) for idx, ob in
                         enumerate(reversed(hierarchy))]
            return "_".join(starmap(name_of, hierarchy))
        else:
            return name_of(obj, True)

    def setup(self):
        for hobj in self.hierarchy_objects:
            cur_manager = ModelManager(
                self.modelname, hobj.name, self.use_facetex,
                self.drang_incval, self.generate_bsp,
                bpy.context.scene.name)
            cur_manager.exp_fname = self.hierarchy_str_for(hobj)
            print("Export filename for {}: {}.iff".format(
                hobj.name, cur_manager.exp_fname))
            self.managers.append(cur_manager)

        for manager in self.managers:
            manager.setup()


class IFFExporter(ExportBackend):

    def export(self):
        """
        Export .iff files from the Blender scene.
        The model is exported as an .iff file, which can be used in
        Wing Commander: Prophecy/Secret Ops.

        Preconditions for a model to be exported:
        1. It must be named according to MAIN_LOD_RE or CHLD_LOD_RE
        2. All of its LODs must be Blender mesh objects.
        3. It must have a LOD 0
        4. All LODs that are to be exported, especially LOD 0, must be visible
           in Blender's viewport.
        """
        export_start = time.perf_counter()

        # Get directory path of output file, plus filename without extension
        modeldir = self.filepath[:self.filepath.rfind(dirsep)]
        modelname = bpy.path.display_name_from_filepath(self.filepath)

        managers = []
        used_names = set()
        main_lod_used = False

        if self.export_active_only:
            # TODO: Traverse object hierarchy and assign export filenames from
            # here.
            if bpy.context.active_object is None:
                raise TypeError("You must have an object selected to export "
                                "only the active object!")

            # Traversing hierarchy here will allow the object export filename
            # to be set, as well as removing the need for traversing the
            # hierarchy in ModelManager.setup(). It's more efficient overall.

            managers.append(HierarchyManager(
                bpy.context.active_object, modelname, modeldir,
                self.use_facetex, self.drang_incval, self.generate_bsp,
                bpy.context.scene.name))

        else:
            for obj in bpy.context.scene.objects:
                if obj.parent is None and not obj.hide:
                    if MAIN_LOD_RE.match(obj.name) and not main_lod_used:
                        main_lod_used = True
                        managers.append(HierarchyManager(
                            obj, modelname, modeldir, self.use_facetex,
                            self.drang_increment, self.generate_bsp,
                            bpy.context.scene.name
                        ))
                        warnings.warn("detail-x LOD naming scheme is "
                                      "deprecated.", DeprecationWarning)
                    else:
                        obj_match = CHLD_LOD_RE.match(obj.name)
                        if obj_match.group(1) not in used_names:
                            managers.append(HierarchyManager(
                                obj, modelname, modeldir, self.use_facetex,
                                self.drang_increment, self.generate_bsp,
                                bpy.context.scene.name
                            ))
                            used_names.add(obj_match.group(1))

        for manager in managers:
            manager.setup()
        print("Export took {} seconds.".format(
            time.perf_counter() - export_start))


def banner(text, width=50):
    str_length = len(text)
    if str_length > width:
        return banner_topbtm + "\n" + text + "\n" + banner_topbtm
    banner_topbtm = "=" * width
    num_sideqs = width // 2 - (str_length + 2) // 2
    banner_mid = (
        "=" * num_sideqs + " " + text + " " + "=" * num_sideqs)
    return banner_topbtm + "\n" + banner_mid + "\n" + banner_topbtm
