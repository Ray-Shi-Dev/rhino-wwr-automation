import rhinoscriptsyntax as rs
import Rhino
def calculate_wwr_massing_flat_v6():
    # 1. Auto-Detect Layers
    all_layers = rs.LayerNames()
    zone_layers = []
    window_layer = None
    
    ignore_list = ["DEFAULT", "SHADING", "SURROUNDING"]
    
    for layer in all_layers:
        clean_name = rs.LayerName(layer, False).upper()
        if clean_name == ".WINDOW":
            window_layer = layer
        elif clean_name in ignore_list or clean_name.startswith("B_"):
            continue
        else:
            zone_layers.append(layer)
            
    if not window_layer:
        print("Error: Could not find the '.WINDOW' layer.")
        return
        
    # 2. Extract Objects
    zone_objs = []
    for zl in zone_layers:
        objs = rs.ObjectsByLayer(zl)
        if objs: zone_objs.extend(objs)
        
    win_objs = rs.ObjectsByLayer(window_layer)
    if not win_objs: return
        
    print("Auto-detected {} Zone blocks and {} Window objects...".format(len(zone_objs), len(win_objs)))
    zones = [rs.coercebrep(obj) for obj in zone_objs if rs.coercebrep(obj)]
    
    # 3. Floor Detection
    floors_dict = {} 
    for z in zones:
        if not z: continue
        bbox = z.GetBoundingBox(True)
        if not bbox: continue
        
        min_z = bbox.Min.Z
        z_height = bbox.Max.Z - min_z
        
        if min_z < -0.5: continue 
        if z_height < 2.0: continue # Ignore 2D artifacts
            
        matched = False
        for f_z in floors_dict.keys():
            if abs(min_z - f_z) < 1.5: 
                floors_dict[f_z].append(z)
                matched = True
                break
        if not matched:
            floors_dict[min_z] = [z]
            
    sorted_floor_zs = sorted(floors_dict.keys())
    print("Detected {} true above-ground floor elevations.".format(len(sorted_floor_zs)))
    
    results = []
    rs.EnableRedraw(False)
    
    # 4. Process Math Per Floor
    for i in range(len(sorted_floor_zs)):
        f_z = sorted_floor_zs[i]
        
        # THE FIX 1: Subtraction Method for exact floor heights
        if i < len(sorted_floor_zs) - 1:
            floor_height = sorted_floor_zs[i+1] - f_z
        else:
            floor_height = 4.5 # Default for the absolute top roof level
            
        floor_top_z = f_z + floor_height
        
        # Perimeter Slicing at 1.2m
        cut_z = f_z + 1.2
        plane = Rhino.Geometry.Plane(Rhino.Geometry.Point3d(0,0,cut_z), Rhino.Geometry.Vector3d.ZAxis)
        
        crvs = []
        for z in zones:
            if not z: continue
            bbox = z.GetBoundingBox(True)
            if bbox.Min.Z < cut_z and bbox.Max.Z > cut_z:
                int_crvs = Rhino.Geometry.Brep.CreateContourCurves(z, plane)
                if int_crvs: crvs.extend(int_crvs)
                
        perimeter_length = 0
        if crvs:
            for_union = [c for c in crvs if c.IsClosed]
            tol = 0.1 
            
            try:
                union_crvs = Rhino.Geometry.Curve.CreateBooleanUnion(for_union, tol)
                if union_crvs: 
                    max_area = -1
                    largest_curve = None
                    for uc in union_crvs:
                        if uc.IsClosed:
                            amp = Rhino.Geometry.AreaMassProperties.Compute(uc)
                            if amp and amp.Area > max_area:
                                max_area = amp.Area
                                largest_curve = uc
                    if largest_curve:
                        perimeter_length = largest_curve.GetLength()
                else: 
                    bb = Rhino.Geometry.BoundingBox.Empty
                    for c in crvs: bb.Union(c.GetBoundingBox(True))
                    perimeter_length = 2 * ((bb.Max.X - bb.Min.X) + (bb.Max.Y - bb.Min.Y))
            except:
                bb = Rhino.Geometry.BoundingBox.Empty
                for c in crvs: bb.Union(c.GetBoundingBox(True))
                perimeter_length = 2 * ((bb.Max.X - bb.Min.X) + (bb.Max.Y - bb.Min.Y))
                
        gross_wall_area = perimeter_length * floor_height
        
        # THE FIX 2: Proportional Glazing Distribution
        glazing_area = 0
        for w_obj in win_objs:
            bbox = rs.BoundingBox(w_obj)
            if not bbox: continue
            
            w_min_z = bbox[0][2]
            w_max_z = bbox[4][2]
            w_height = w_max_z - w_min_z
            
            if w_height <= 0.01: continue # Prevent division by zero
            
            # Calculate how much of the window physically sits in this floor's zone
            overlap_min = max(w_min_z, f_z)
            overlap_max = min(w_max_z, floor_top_z)
            overlap_height = overlap_max - overlap_min
            
            if overlap_height > 0.01: # The window is inside this floor
                ratio = overlap_height / w_height
                
                if rs.IsCurve(w_obj) and rs.IsCurveClosed(w_obj):
                    area_data = rs.CurveArea(w_obj)
                    if area_data: glazing_area += (area_data[0] * ratio)
                elif rs.IsSurface(w_obj) or rs.IsPolysurface(w_obj):
                    area_data = rs.SurfaceArea(w_obj)
                    if area_data: glazing_area += (area_data[0] * ratio)
                    
        wwr = 0
        if gross_wall_area > 0:
            wwr = (glazing_area / gross_wall_area) * 100
            
        results.append({
            "Floor": i+1,
            "Elevation Z (m)": round(f_z, 2),
            "Height (m)": round(floor_height, 2),
            "Gross Perimeter (m)": round(perimeter_length, 2),
            "Gross Wall Area (sqm)": round(gross_wall_area, 2),
            "Glazing Area (sqm)": round(glazing_area, 2),
            "WWR %": round(wwr, 2)
        })
        print("Processed Floor {}/{}...".format(i+1, len(sorted_floor_zs)))
        
    rs.EnableRedraw(True)
    
    # 5. Export
    filename = rs.SaveFileName("Save True Area WWR Results", "CSV Files (*.csv)|*.csv||")
    if filename:
        with open(filename, 'w') as f:
            f.write("Floor,Elevation Z (m),Height (m),Gross Perimeter (m),Gross Wall Area (sqm),Glazing Area (sqm),WWR %\n")
            for r in results:
                f.write("{},{},{},{},{},{},{}\n".format(
                    r["Floor"], r["Elevation Z (m)"], r["Height (m)"], r["Gross Perimeter (m)"], 
                    r["Gross Wall Area (sqm)"], r["Glazing Area (sqm)"], r["WWR %"]))
        print(">>> SUCCESS: True Area Table exported to " + filename)
if name == "__main__":
    calculate_wwr_massing_flat_v6()
