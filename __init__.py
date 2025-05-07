bl_info = {
    "name": "IFC Class Hierarchy Viewer",
    "author": "Jakob Beetz",
    "version": (1, 1),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > IFC Hierarchy Tab",
    "description": "Displays IFC class hierarchy (supertypes and subtypes) of selected object",
    "category": "BIM",
}

import bpy
import os
import sys
import site
import tempfile
import subprocess
import importlib

# Fix Python path
site_packages_path = os.path.expanduser('~') + "/AppData/Roaming/Python/Python311/site-packages"
if site_packages_path not in sys.path:
    sys.path.append(site_packages_path)

def install_and_import(package):
    try:
        importlib.import_module(package)
    except ImportError:
        python_executable = sys.executable
        subprocess.check_call([python_executable, "-m", "ensurepip"])
        subprocess.check_call([python_executable, "-m", "pip", "install", package, "--user"])
    finally:
        globals()[package] = importlib.import_module(package)

# Install missing packages
install_and_import('networkx')
install_and_import('matplotlib')
install_and_import('netgraph') 
install_and_import('pydot') 
install_and_import('graphviz') 


import networkx as nx
import matplotlib.pyplot as plt
import ifcopenshell
import ifcopenshell.api
import bonsai.tool as tool
from pprint import pprint

# --- Utility Functions ---

def get_selected_ifc_class():
    
    obj = bpy.context.active_object
    if obj is None:
        return None
    ifc_model = tool.Ifc.get()
    ifc_class=None
    if ifc_model is None:
        print("No IFC file loaded.")
        return None
    else: 
        print('found model ')
    if ifc_model:
        if hasattr(obj, "BIMObjectProperties") and obj.BIMObjectProperties.ifc_definition_id:
            ifc_id = int(obj.BIMObjectProperties.ifc_definition_id)
            print(f"Found BIMObjectProperties id: {ifc_id}")
            ifc_entity = ifc_model.by_id(ifc_id)
            if ifc_entity:
                print(f"IFC Class: {ifc_entity.is_a()}")
                return(ifc_entity.is_a())
        elif "ifc_definition_id" in obj:
            ifc_id = int(obj["ifc_definition_id"])
            print(f"Found custom property id: {ifc_id}")
            ifc_entity = ifc_model.by_id(ifc_id)
            if ifc_entity:
                print(f"IFC Class: {ifc_entity.is_a()}")
                
        else:
            print("No IFC linkage found.")
    else:
        print("No IFC file loaded.")
    

    
    return None

def build_ifc_hierarchy_graph(ifc_class_name):
    graph = nx.DiGraph()

    schema = ifcopenshell.ifcopenshell_wrapper.schema_by_name("IFC4")  # Assume IFC4 (could be dynamic)

    if not schema.declaration_by_name(ifc_class_name):
        return graph

    def add_supertypes(entity_name):
        entity = schema.declaration_by_name(entity_name)
        # Add node with is_selected attribute for the current selection
        is_selected = (entity.name() == ifc_class_name)
        graph.add_node(entity.name(), is_selected=is_selected)
        supertype = entity.supertype()
        if supertype:
            graph.add_edge(supertype.name(), entity.name())
            add_supertypes(supertype.name())

    def add_subtypes(entity_name):
        entity = schema.declaration_by_name(entity_name)
        # Add node with is_selected attribute for the current selection
        is_selected = (entity.name() == ifc_class_name)
        graph.add_node(entity.name(), is_selected=is_selected)
        for subtype in entity.subtypes():
            graph.add_edge(entity.name(), subtype.name())
            add_subtypes(subtype.name())

    add_supertypes(ifc_class_name)
    add_subtypes(ifc_class_name)

    return graph

def build_recursive_attribute_graph(ifc_entity, blacklist=None, max_depth=1):
    if blacklist is None:
        blacklist = ['ObjectPlacement', 'PlacementRelTo', 'RelativePlacement', 'OwnerHistory']

    graph = nx.DiGraph()
    edge_labels={}
    
    # Get the entity ID of the selected entity for highlighting
    selected_entity_id = ifc_entity.id()
    
    def add_entity_to_graph(entity, current_depth):
        if entity is None or not isinstance(entity, ifcopenshell.entity_instance):
            return
        
        entity_name = f"#{entity.id()} {entity.is_a()}"
        # Mark if this is the selected entity
        is_selected = (entity.id() == selected_entity_id)
        graph.add_node(entity_name, label=entity_name, is_selected=is_selected)
        print(f"{entity_name}, depth={current_depth}")
        
        if current_depth > max_depth:
            return
        
        # Forward relationships using get_info(False)
        for attr_name in entity.get_info(False):
            if attr_name in blacklist:
                continue

            attr_value = getattr(entity, attr_name, None)
            if isinstance(attr_value, ifcopenshell.entity_instance):
                related_entity_name = f"#{attr_value.id()} {attr_value.is_a()}"
                el = graph.add_edge(entity_name, related_entity_name, label=attr_name)
                edge_labels[el]=attr_name
                add_entity_to_graph(attr_value, current_depth + 1)
            elif isinstance(attr_value, (list, tuple)):
                for item in attr_value:
                    if isinstance(item, ifcopenshell.entity_instance):
                        related_entity_name = f"#{item.id()} {item.is_a()}"
                        el= graph.add_edge(entity_name, related_entity_name, label=attr_name)
                        edge_labels[el]=attr_name
                        add_entity_to_graph(item, current_depth + 1)

        # Inverse relationships using tool.Ifc.get().get_inverse() with a single attribute index
        if current_depth != 0:
            return
                
        inverse_relationships = tool.Ifc.get().get_inverse(entity, True, with_attribute_indices=True)
        
        for inverse_rel in inverse_relationships:
            if isinstance(inverse_rel, tuple):
                # Ensure the tuple has the expected number of elements
                if len(inverse_rel) == 2:
                    inverse_entity, inverse_attr_index = inverse_rel
                    if isinstance(inverse_entity, ifcopenshell.entity_instance) and not (entity.is_a() == "IfcOwnerHistory"):
                        ref_entity_name = f"#{inverse_entity.id()} {inverse_entity.is_a()}"
                        print(f"Inverse relationship: {ref_entity_name} -> {entity_name}")            
                        # Lookup attribute name using the single index
                        inverse_attr_name = inverse_entity.attribute_name(inverse_attr_index)
                        el = graph.add_edge(ref_entity_name, entity_name, label=f"(inverse) {inverse_attr_name}")
                        edge_labels[el]=attr_name
                        #just add this, go over maximum depth of 3 
                        add_entity_to_graph(inverse_entity, current_depth + 3)

    add_entity_to_graph(ifc_entity, 0)
    return graph, edge_labels

import netgraph

def draw_graph_to_image(graph, edge_labels, title="IFC Class Hierarchy", use_dot_layout=True):
    temp_dir = tempfile.gettempdir()
    png_path = os.path.join(temp_dir, "ifc_hierarchy_graph.png")
    graphml_path = os.path.join(temp_dir, "ifc_hierarchy_graph.graphml")

    # Save the graph as a GraphML file
    # nx.write_graphml(graph, graphml_path)
    default_dpi = plt.rcParams['figure.dpi']

    # Create a Matplotlib figure and axes
    fig = plt.figure(figsize=(2048/ default_dpi, 2048 / default_dpi), dpi=default_dpi)
    if use_dot_layout:
        # Use Graphviz's dot layout
        try:
            # Create a pydot graph with box-shaped nodes
            pydot_graph = nx.nx_pydot.to_pydot(graph)
            
            # Set node attributes: shape=box and add attributes to labels
            for node in pydot_graph.get_nodes():
                node_name = node.get_name().strip('"')
                if node_name in graph.nodes:
                    # Get node attributes
                    attrs = graph.nodes[node_name]
                    # Create a label with node attributes
                    label_parts = [node_name]
                    for attr, value in attrs.items():
                        if attr != 'label' and attr != 'is_selected':  # Avoid duplicating the label
                            label_parts.append(f"{attr}: {value}")
                    
                    # Set the new label and box shape
                    node.set_label('"' + '\\n'.join(label_parts) + '"')
                    node.set_shape('box')
                    node.set_fontname('Arial-Bold')
                    
                    # Set color to red if this is the selected node
                    if 'is_selected' in attrs and attrs['is_selected']:
                        node.set_color('red')
                        node.set_style('filled')
                        node.set_fillcolor('red')
                        node.set_fontcolor('white')
            
            pydot_graph.set_rankdir("LR")
            pydot_graph.set_graph_defaults(size="30.83,30.83!", dpi="96")
            pydot_graph.set_graph_defaults(fontname="Arial", fontsize="14")
            pydot_graph.set("layout", "dot")
            pydot_graph.write_png(png_path)
            
        except ImportError:
            print("Graphviz layout requested but pygraphviz or pydot is not installed.")
            pos = nx.spring_layout(graph)  # Fallback to spring layout
        # Use netgraph to draw the graph
        pos = nx.spring_layout(graph)  # Default layout

    # Draw the graph using the selected layout
        # Create node color map based on selection status
        node_colors = []
        for node in graph.nodes():
            if graph.nodes[node].get('is_selected', False):
                node_colors.append('red')
            else:
                node_colors.append('lightblue')
                
        nx.draw(graph, pos, with_labels=True, arrows=True, node_size=2000, 
                node_color=node_colors, font_size=10, edge_color='gray')
        ax = fig.add_subplot(111)
        
        # Create node color map for netgraph
        node_color_dict = {}
        for node in graph.nodes():
            if graph.nodes[node].get('is_selected', False):
                node_color_dict[node] = 'red'
            else:
                node_color_dict[node] = 'blue'
        
        # Use netgraph to draw the graph
        plot_instance = netgraph.Graph(
           graph,
           node_layout='spring',
           node_color=node_color_dict,
           ax=ax,
           arrows=True,
           node_labels=True,
           labels=True,
           edge_labels=False,
           # Increase font size and set color to black
           label_kwargs={'fontsize': 10, 'color': 'white'},
           node_label_fontdict=dict(size=9), 
           # node_label_offset=0.0,
           edge_label_kwargs={'fontsize': 10, 'color': 'black'},
           node_layout_kwargs={'iterations': 50000},
           edge_layout='curved'
       )


    plt.title(title)
    plt.axis('off')
    #plt.savefig(png_path, bbox_inches='tight')
    plt.close()

    return png_path

def load_image_in_blender(png_path):
    if "IFCHierarchy" in bpy.data.images:
        bpy.data.images.remove(bpy.data.images["IFCHierarchy"])
    img = bpy.data.images.load(png_path)
    img.name = "IFCHierarchy"

    for area in bpy.context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            area.spaces.active.image = img
            break
    else:
        print("No IMAGE_EDITOR open.")

# --- Blender Operator ---

class IFC_OT_GenerateHierarchy(bpy.types.Operator):
    bl_idname = "ifc.generate_hierarchy_graph"
    bl_label = "Generate IFC Hierarchy"
    bl_description = "Generate IFC supertypes and subtypes hierarchy graph for selected object"

    def execute(self, context):
        ifc_class = get_selected_ifc_class()
        if not ifc_class:
            self.report({'ERROR'}, "No IFC class found for selected object.")
            return {'CANCELLED'}

        graph = build_ifc_hierarchy_graph(ifc_class)
        if len(graph.nodes) == 0:
            self.report({'ERROR'}, "Could not build hierarchy graph.")
            return {'CANCELLED'}

        png_path = draw_graph_to_image(graph, title=f"IFC Hierarchy: {ifc_class}", edge_labels=[])
        load_image_in_blender(png_path)

        self.report({'INFO'}, f"Graph generated for {ifc_class}")
        return {'FINISHED'}

class IFC_OT_GenerateAttributeGraph(bpy.types.Operator):
    bl_idname = "ifc.generate_attribute_graph"
    bl_label = "Generate Attribute Graph"
    bl_description = "Generate a graph of all attributes and relationships for the selected IFC entity"

    def execute(self, context):
        ifc_class = get_selected_ifc_class()
        if not ifc_class:
            self.report({'ERROR'}, "No IFC class found for selected object.")
            return {'CANCELLED'}

        ifc_entity = tool.Ifc.get().by_id(int(bpy.context.active_object.BIMObjectProperties.ifc_definition_id))
        blacklist = ['Representation', 'ObjectPlacement', 'PlacementRelTo', 'RelativePlacement', 'OwnerHistory']
        max_depth = 5
        graph, edge_labels = build_recursive_attribute_graph(ifc_entity, blacklist=blacklist, max_depth=max_depth)
        if len(graph.nodes) == 0:
            self.report({'ERROR'}, "Could not build attribute graph.")
            return {'CANCELLED'}

        png_path = draw_graph_to_image(graph, edge_labels, title=f"Attributes of {ifc_class}")
        load_image_in_blender(png_path)

        self.report({'INFO'}, f"Attribute graph generated for {ifc_class}")
        return {'FINISHED'}

# --- Blender Panel ---

class IFC_PT_HierarchyPanel(bpy.types.Panel):
    bl_label = "IFC Class Hierarchy"
    bl_idname = "IFC_PT_hierarchy_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'IFC Hierarchy'

    def draw(self, context):
        layout = self.layout
        layout.operator("ifc.generate_hierarchy_graph", text="Show IFC Class Hierarchy")
        layout.operator("ifc.generate_attribute_graph", text="Show Attribute Graph in Image")  # New button

# --- Registration ---

classes = [
    IFC_OT_GenerateHierarchy,
    IFC_OT_GenerateAttributeGraph,  
    IFC_PT_HierarchyPanel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
