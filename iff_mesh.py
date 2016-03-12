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

# Classes for WCP/SO IFF Meshes
from . import iff
import warnings


class MeshLODForm(iff.IffForm):
    def __init__(self, LOD, version=12):
        # No call to superclass constructor because we set the same values
        # in this constructor
        self._name = "{!s:0>4}".format(LOD)
        self._mesh_form = iff.IffForm("MESH")
        self._geom_form = iff.IffForm("{!s:0>4}".format(version))
        self._name_chunk = iff.IffChunk("NAME")
        self._vert_chunk = iff.IffChunk("VERT")
        self._vtnm_chunk = iff.IffChunk("VTNM")
        self._fvrt_chunk = iff.IffChunk("FVRT")
        self._face_chunk = iff.IffChunk("FACE")
        self._cntr_chunk = iff.IffChunk("CNTR")
        self._radi_chunk = iff.IffChunk("RADI")
        self._geom_form.add_member(self._name_chunk)
        self._geom_form.add_member(self._vert_chunk)
        self._geom_form.add_member(self._vtnm_chunk)
        self._geom_form.add_member(self._fvrt_chunk)
        self._geom_form.add_member(self._face_chunk)
        self._geom_form.add_member(self._cntr_chunk)
        self._geom_form.add_member(self._radi_chunk)
        self._mesh_form.add_member(self._geom_form)
        self._members = [self._mesh_form]

    def set_name(self, name):
        # Check data types before adding to respective chunks
        if self._name_chunk.has_members():
            self._name_chunk.clear_members()
        if isinstance(name, str):
            self._name_chunk.add_member(name)
        else:
            raise TypeError("Name of this mesh LOD must be a string!")

    def add_vertex(self, vx, vy, vz):
        if not (isinstance(vx, float) and
                isinstance(vy, float) and
                isinstance(vz, float)):
            raise TypeError("The vertex coordinates must be floating point"
                            " values!")

        self._vert_chunk.add_member(vx)
        self._vert_chunk.add_member(vy)
        self._vert_chunk.add_member(vz)

    def add_normal(self, nx, ny, nz):
        if not (isinstance(nx, float) and
                isinstance(ny, float) and
                isinstance(nz, float)):
            raise TypeError("The normal vector must be floating point values!")

        self._vtnm_chunk.add_member(nx)
        self._vtnm_chunk.add_member(ny)
        self._vtnm_chunk.add_member(nz)

    def add_fvrt(self, vert_idx, vtnm_idx, uv_x, uv_y):
        if (not(isinstance(vert_idx, int) and
                isinstance(vtnm_idx, int))):
            raise TypeError("The vertex and vertex normal indices must"
                            " be integers!")
        if (not(isinstance(uv_x, float) and
                isinstance(uv_y, float))):
            raise TypeError("The UV coordinates must be floating point"
                            " values!")

        self._fvrt_chunk.add_member(vert_idx)
        self._fvrt_chunk.add_member(vtnm_idx)
        self._fvrt_chunk.add_member(uv_x)
        self._fvrt_chunk.add_member(uv_y)

    def add_face(self, vtnm_idx, dplane, texnum,
                 fvrt_idx, num_verts, light_flags, alt_mat=0x7F0096FF):
        if not isinstance(vtnm_idx, int):
            raise TypeError("Vertex normal index must be an integer!")
        if not isinstance(dplane, float):
            raise TypeError("D-Plane value must be a floating point number!")
        if not isinstance(texnum, int):
            raise TypeError("Texture number must be an integer!")
        if not isinstance(fvrt_idx, int):
            raise TypeError("First FVRT index must be an integer!")
        if not isinstance(num_verts, int):
            raise TypeError("Number of vertices must be an integer!")
        if not isinstance(light_flags, int):
            raise TypeError("Lighting wordflag must be an integer!")
        if not isinstance(alt_mat, int):
            raise TypeError("Alternate MAT must be an integer!")

        self._face_chunk.add_member(vtnm_idx)  # Face normal
        self._face_chunk.add_member(dplane)  # D-Plane
        self._face_chunk.add_member(texnum)  # Texture number
        self._face_chunk.add_member(fvrt_idx)  # Index of face's first FVRT
        self._face_chunk.add_member(num_verts)  # Number of vertices
        self._face_chunk.add_member(light_flags)  # Lighting flags
        self._face_chunk.add_member(alt_mat)  # Unknown (alternate MAT?)

    def set_center(self, cx, cy, cz):
        if self._cntr_chunk.has_members():
            self._cntr_chunk.clear_members()
        if (isinstance(cx, float) and
                isinstance(cy, float) and
                isinstance(cz, float)):
            self._cntr_chunk.add_member(cx)
            self._cntr_chunk.add_member(cy)
            self._cntr_chunk.add_member(cz)
        else:
            raise TypeError("Center coordinates must be floating point"
                            " values!")

    def set_radius(self, radius):
        if self._radi_chunk.has_members():
            self._radi_chunk.clear_members()
        if isinstance(radius, float):
            self._radi_chunk.add_member(radius)
        else:
            raise TypeError("Radius must be a floating point value!")

    # Do not use! These methods are only here for backwards compatibility
    def get_name_chunk(self):
        warnings.warn("get_name_chunk is deprecated!", DeprecationWarning)
        return self._name_chunk

    def get_vert_chunk(self):
        warnings.warn("get_vert_chunk is deprecated!", DeprecationWarning)
        return self._vert_chunk

    def get_vtnm_chunk(self):
        warnings.warn("get_vtnm_chunk is deprecated!", DeprecationWarning)
        return self._vtnm_chunk

    def get_fvrt_chunk(self):
        warnings.warn("get_fvrt_chunk is deprecated!", DeprecationWarning)
        return self._fvrt_chunk

    def get_face_chunk(self):
        warnings.warn("get_face_chunk is deprecated!", DeprecationWarning)
        return self._face_chunk

    def get_cntr_chunk(self):
        warnings.warn("get_cntr_chunk is deprecated!", DeprecationWarning)
        return self._cntr_chunk

    def get_radi_chunk(self):
        warnings.warn("get_radi_chunk is deprecated!", DeprecationWarning)
        return self._radi_chunk


class MeshIff(iff.IffFile):
    def __init__(self, filename, include_far_chunk,
                 dranges=[float(0), float(400), float(800)]):

        if not isinstance(include_far_chunk, bool):
            raise TypeError("include_far_chunk must be a boolean value!")

        if isinstance(dranges, list):
            for drange in dranges:
                if not isinstance(drange, float):
                    raise TypeError("Each LOD range must be a float!")
        else:
            raise TypeError("dranges must be a list or tuple!")

        # Initialize an empty mesh IFF file, initialize data structures, etc.
        super().__init__("DETA", filename)

        self._mrang = iff.IffChunk("RANG", dranges)
        self.root_form.add_member(self._mrang)

        self._mmeshes = iff.IffForm("MESH")
        self.root_form.add_member(self._mmeshes)

        self._mhard = iff.IffForm("HARD")
        self.root_form.add_member(self._mhard)

        self._mcoll = iff.IffForm("COLL")
        self.root_form.add_member(self._mcoll)

        if include_far_chunk:
            self._mfar = iff.IffChunk("FAR ", [float(0), float(900000)])
            self.root_form.add_member(self._mfar)

    def make_coll_sphr(self, X, Y, Z, radius):
        if self._mcoll.has_members():
            for mem in range(self._mcoll.get_num_members()):
                self._mcoll.remove_member(mem)

        _mcollsphr = iff.IffChunk("SPHR")
        _mcollsphr.add_member(X)
        _mcollsphr.add_member(Y)
        _mcollsphr.add_member(Z)
        _mcollsphr.add_member(radius)
        self._mcoll.add_member(_mcollsphr)

    def make_coll_tree(self):
        return NotImplemented

    def add_hardpt(self, x, y, z, rot_matrix, name):
        hardpt = iff.IffChunk("HARD")
        hardpt.add_member(rot_matrix[0][0])
        hardpt.add_member(rot_matrix[0][1])
        hardpt.add_member(rot_matrix[0][2])
        hardpt.add_member(x)
        hardpt.add_member(rot_matrix[1][0])
        hardpt.add_member(rot_matrix[1][1])
        hardpt.add_member(rot_matrix[1][2])
        hardpt.add_member(y)
        hardpt.add_member(rot_matrix[2][0])
        hardpt.add_member(rot_matrix[2][1])
        hardpt.add_member(rot_matrix[2][2])
        hardpt.add_member(z)
        hardpt.add_member(name)
        self._mhard.add_member(hardpt)

    def remove_hardpt(self, hp_idx):
        self._mhard.remove_member(hp_idx)

    def remove_hardpts(self):
        self._mhard.clear_members(mem)

    def add_lod(self, lod):
        if isinstance(lod, MeshLODForm):
            self._mmeshes.add_member(lod)

    def set_dranges(self, dranges):
        if isinstance(dranges, list) or isinstance(dranges, tuple):
            for drange in dranges:
                if not isinstance(drange, float):
                    raise TypeError("Each LOD range must be a float!")
        else:
            raise TypeError("dranges must be a list or tuple!")

        self._mrang.clear_members()
        for drange in dranges:
            self._mrang.add_member(drange)

    def get_meshes_form(self):
        warnings.warn("get_meshes_form is deprecated!", DeprecationWarning)
        return self._mmeshes
